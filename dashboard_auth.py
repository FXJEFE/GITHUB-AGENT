# -*- coding: utf-8 -*-
"""
dashboard_auth.py - local login + session + CSRF for the FXJEFE dashboard.

The dashboard exposes destructive controls (restart servers, run pipelines,
kill processes). It binds 127.0.0.1 only, so it is not reachable from the
network - but a malicious web page open in a local browser could still script
requests at it (DNS-rebinding / CSRF). This module closes that gap:

  * password login; hash stored in db/dashboard_auth.json (werkzeug PBKDF2)
  * every route needs a session except /login and /setup-password
  * Host-header allowlist            -> blocks DNS-rebinding
  * SameSite=Strict cookies + an X-CSRF-Token check on state-changing requests

Pure Flask/werkzeug - no OS-specific code; runs identically on Windows/Linux.

Usage from dashboard_hub.py:
    from dashboard_auth import init_auth, reset_password
    init_auth(app, DB_ROOT, port)        # once, before app.run()
"""

import json
import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import request, session, redirect, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

# Paths reachable without a session. The Host check still applies to these.
_PUBLIC_PATHS = {"/login", "/setup-password"}
_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _load(auth_file: Path) -> dict:
    try:
        return json.loads(auth_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(auth_file: Path, data: dict) -> None:
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_configured(auth_file: Path) -> bool:
    return bool(_load(auth_file).get("password_hash"))


def reset_password(db_root) -> bool:
    """Clear the stored password so the next launch shows the setup page.
    Backs the 'python dashboard_hub.py --reset-password' flag."""
    auth_file = Path(db_root) / "dashboard_auth.json"
    data = _load(auth_file)
    data.pop("password_hash", None)
    _save(auth_file, data)
    return True


# -- luxury dark login/setup page (self-contained; emblem embedded as data URI) --
import base64 as _b64
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def _emblem_data_uri() -> str:
    """FXJEFE emblem as a base64 data URI so the login page needs no pre-auth
    asset route. Returns '' if the image is not on the device."""
    try:
        img = Path(__file__).parent / "personal_ai_training" / "FXJEFEprofile.jpg"
        if img.exists():
            b = _b64.b64encode(img.read_bytes()).decode("ascii")
            return "data:image/jpeg;base64," + b
    except Exception:
        pass
    return ""


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
 :root{{--gold:#c8a24c;--gold2:#e2c983;--text:#e9e6db;--dim:rgba(233,230,219,.45);--line:rgba(201,162,76,.18)}}
 *{{box-sizing:border-box}}
 body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
   font-family:'Inter',Segoe UI,sans-serif;color:var(--text);
   background:radial-gradient(1000px 600px at 75% -10%,rgba(200,162,76,.12),transparent 60%),
     radial-gradient(800px 500px at 15% 110%,rgba(137,168,201,.06),transparent 55%),
     linear-gradient(180deg,#0b0e14,#0a0d12)}}
 .box{{position:relative;background:linear-gradient(180deg,rgba(20,25,38,.95),rgba(15,19,28,.95));
   border:1px solid var(--line);border-radius:16px;padding:40px 38px 34px;width:352px;
   box-shadow:0 24px 70px rgba(0,0,0,.6);text-align:center}}
 .box::after{{content:'';position:absolute;left:0;right:0;bottom:0;height:1px;
   background:linear-gradient(90deg,transparent,var(--gold),transparent);opacity:.75}}
 .emblem{{width:84px;height:84px;border-radius:50%;object-fit:cover;margin:0 auto 18px;display:block;
   border:1px solid rgba(200,162,76,.55);box-shadow:0 0 0 5px rgba(200,162,76,.07),0 10px 26px rgba(0,0,0,.55)}}
 h1{{font-family:'Playfair Display',Georgia,serif;font-size:1.35rem;font-weight:700;letter-spacing:.5px;margin:0 0 2px}}
 .sub-brand{{font-size:.58rem;letter-spacing:5px;color:var(--gold);text-transform:uppercase;margin-bottom:16px}}
 p{{font-size:.78rem;color:var(--dim);margin:0 0 20px}}
 input{{width:100%;background:rgba(0,0,0,.35);border:1px solid var(--line);
   color:var(--text);border-radius:9px;padding:12px 14px;margin:7px 0;font-size:.9rem;font-family:'Inter',sans-serif;outline:none;transition:border-color .2s}}
 input:focus{{border-color:var(--gold)}}
 input::placeholder{{color:var(--dim)}}
 button{{width:100%;background:linear-gradient(180deg,var(--gold2),var(--gold));color:#1a1206;border:0;border-radius:9px;
   padding:13px;margin-top:14px;font-weight:600;cursor:pointer;letter-spacing:2px;font-size:.72rem;text-transform:uppercase;font-family:'Inter',sans-serif;transition:filter .2s}}
 button:hover{{filter:brightness(1.08)}}
 .err{{color:#d1666e;font-size:.76rem;min-height:1em;margin-top:10px}}
</style></head><body><div class="box">
 {emblem}
 <h1>FXJEFE</h1><div class="sub-brand">Command Central</div><p>{subtitle}</p>
 <form method="post" onsubmit="try{{sessionStorage.setItem('fxj_tab','1')}}catch(e){{}}">{fields}<button type="submit">{action}</button></form>
 <div class="err">{error}</div>
</div></body></html>"""


def _render(title, subtitle, action, fields, error=""):
    uri = _emblem_data_uri()
    emblem = f'<img class="emblem" src="{uri}" alt="FXJEFE">' if uri else ""
    return _PAGE.format(title=title, subtitle=subtitle, action=action,
                        fields=fields, error=error, emblem=emblem)


def init_auth(app, db_root, port):
    """Wire login, session and CSRF onto the Flask app. Call once after the
    app is created and before app.run()."""
    db_root = Path(db_root)
    db_root.mkdir(parents=True, exist_ok=True)
    auth_file = db_root / "dashboard_auth.json"
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    # Persistent secret key -> sessions SURVIVE dashboard restarts / reboots, so
    # you are no longer re-prompted for the password on every boot (the cause of
    # the "log in again / duplicate login each boot" problem). The key is
    # generated once and stored 0600 in db/dashboard_secret.key. Delete that file
    # to force a global re-login. The dashboard is 127.0.0.1-only with a Host
    # allowlist + CSRF, so a long-lived local session is an acceptable trade-off.
    secret_file = db_root / "dashboard_secret.key"
    try:
        if secret_file.exists():
            app.secret_key = secret_file.read_text(encoding="utf-8").strip()
        else:
            app.secret_key = secrets.token_hex(32)
            secret_file.write_text(app.secret_key, encoding="utf-8")
            try:
                os.chmod(secret_file, 0o600)
            except Exception:
                pass
    except Exception:
        app.secret_key = secrets.token_hex(32)  # fall back to ephemeral on I/O error

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        # Persistent cookie (session.permanent=True in _begin_session) with a long
        # lifetime so Brave keeps you logged in across reboots.
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )

    def _begin_session():
        session["authed"] = True
        session["csrf"] = secrets.token_hex(16)
        # Non-persistent (browser-session) cookie: combined with the per-tab
        # sessionStorage gate in the dashboard, closing/reopening a tab requires
        # the password again, and closing the browser logs out entirely.
        session.permanent = False

    @app.before_request
    def _gate():
        # 1. Host-header allowlist - defeats DNS-rebinding. Applies to all.
        if request.host not in allowed_hosts:
            abort(403)

        path = request.path
        if path in _PUBLIC_PATHS:
            return None

        # 2. First run with no password -> force the setup page.
        if not _is_configured(auth_file):
            return None if path == "/setup-password" else redirect("/setup-password")

        # 3. Auth gate.
        if not session.get("authed"):
            if path.startswith("/api/"):
                return jsonify({"error": "auth required"}), 401
            return redirect("/login")

        # 4. CSRF - state-changing requests need the matching header.
        if request.method in _STATE_METHODS:
            token = request.headers.get("X-CSRF-Token", "")
            if not token or token != session.get("csrf"):
                return jsonify({"error": "bad or missing CSRF token"}), 403
        return None

    @app.after_request
    def _csrf_cookie(resp):
        # Expose the session CSRF token to same-site JS (double-submit pattern).
        if session.get("authed") and session.get("csrf"):
            resp.set_cookie("csrf_token", session["csrf"],
                            samesite="Strict", httponly=False, secure=False)
        return resp

    @app.route("/setup-password", methods=["GET", "POST"])
    def setup_password():
        if _is_configured(auth_file):
            return redirect("/login")
        error = ""
        if request.method == "POST":
            pw = request.form.get("password", "")
            pw2 = request.form.get("confirm", "")
            # Min length is intentionally lenient: the dashboard is local-only
            # (127.0.0.1 + Host allowlist + CSRF), so the password just keeps
            # accidental same-machine browser tabs out, not network attackers.
            if len(pw) < 4:
                error = "Password must be at least 4 characters."
            elif pw != pw2:
                error = "Passwords do not match."
            else:
                d = _load(auth_file)
                d["password_hash"] = generate_password_hash(pw)
                _save(auth_file, d)
                _begin_session()
                return redirect("/")
        fields = ('<input type="password" name="password" placeholder="Choose a password" autofocus>'
                  '<input type="password" name="confirm" placeholder="Confirm password">')
        return _render("Set Password", "First run - set your dashboard password.",
                       "SET PASSWORD", fields, error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not _is_configured(auth_file):
            return redirect("/setup-password")
        error = ""
        if request.method == "POST":
            pw = request.form.get("password", "")
            if check_password_hash(_load(auth_file).get("password_hash", ""), pw):
                _begin_session()
                return redirect("/")
            error = "Wrong password."
        fields = '<input type="password" name="password" placeholder="Password" autofocus>'
        return _render("Login", "Enter your dashboard password.",
                       "UNLOCK", fields, error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect("/login")
