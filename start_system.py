#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — SYSTEM LAUNCHER  (boot / login entry point)        ║
║   Starts the Command Central dashboard AND the full stack together.  ║
╚══════════════════════════════════════════════════════════════════════╝

This is the ONE thing to auto-start at login. It brings up, in order:

  1. dashboard_hub.py        — Command Central web UI on http://127.0.0.1:3777
  2. start_fullstack.py      — venv/deps/config + Ollama (fast tool model) +
                               Telegram bot, supervised.

Then it supervises both children and opens the dashboard in a browser.

Install at login:
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
    powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 -Uninstall

Run manually:
    python launchers/start_system.py
    python launchers/start_system.py --no-browser
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# Reuse the kill-on-close Job Object helper from the full-stack launcher so a
# hard kill of THIS process also takes down the dashboard + full stack.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from start_fullstack import _enter_kill_on_close_job, best_python  # noqa: E402

IS_WINDOWS = os.name == "nt"
ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")
# Canonical code tree is src/. The dashboard there resolves PROJECT_ROOT to src,
# so it launches src/agent_v2.py (the fixed agent). The identical copy at the
# repo root would launch the stale root duplicate — keep this pointed at src/.
DASHBOARD = ROOT / "src" / "dashboard_hub.py"
if not DASHBOARD.exists():
    DASHBOARD = ROOT / "dashboard_hub.py"  # fallback for older layouts
FULLSTACK = ROOT / "launchers" / "start_fullstack.py"
CONFIG_PATH = ROOT / "larry_config.json"
LOG_DIR = ROOT / "logs"

_children: list[dict] = []
_stop = False

# Single-instance lock. Without this, two launchers (e.g. the Startup shortcut
# firing alongside a manual run) each bring up a full stack — two Telegram bots
# then long-poll the SAME token and Telegram 409-conflicts them, so the bot
# stops replying, and you get a duplicate browser tab. The lock makes the
# second launcher exit immediately.
LOCK_FILE = ROOT / "logs" / ".start_system.lock"


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID is currently running. Avoids os.kill on
    Windows (where signal 0 would TERMINATE the target rather than probe it)."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in out.stdout
        except Exception:
            return True  # fail safe: assume alive so we don't double-launch
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_singleton() -> bool:
    """Claim the single-instance lock. Returns False if another live launcher
    already holds it (caller should then exit). Fails open on any I/O error."""
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            try:
                other = int((LOCK_FILE.read_text(encoding="utf-8").strip() or "0"))
            except Exception:
                other = 0
            if other and other != os.getpid() and _pid_alive(other):
                return False
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(_release_singleton)
        return True
    except Exception:
        return True


def _release_singleton() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except Exception:
        pass


def log(msg: str, level: str = "INFO") -> None:
    print(f"[{datetime.now():%H:%M:%S}] {level:<5} {msg}", flush=True)


def _python() -> str:
    # Run the dashboard + full stack under the interpreter that has the deps.
    return best_python()


def _dashboard_hostport() -> tuple[str, int]:
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        d = cfg.get("dashboard", {}) or {}
        return d.get("host", "127.0.0.1"), int(d.get("port", 3777))
    except Exception:
        return "127.0.0.1", 3777


def _port_open(host: str, port: int) -> bool:
    host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _spawn(name: str, argv: list[str], cwd: Path, logfile: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOG_DIR / logfile, "a", encoding="utf-8")
    fh.write(f"\n===== {name} started {datetime.now().isoformat()} =====\n")
    fh.flush()
    proc = subprocess.Popen(argv, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT)
    _children.append({"name": name, "proc": proc, "log": fh})
    log(f"Started {name} (PID {proc.pid}) -> logs/{logfile}")


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def teardown() -> None:
    for child in reversed(_children):
        proc = child["proc"]
        if proc.poll() is None:
            log(f"Stopping {child['name']} (PID {proc.pid}) ...")
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as e:
                log(f"Error stopping {child['name']}: {e}", "WARN")
        try:
            child["log"].close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Larry G-Force system launcher (dashboard + full stack).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the dashboard in a browser.")
    parser.add_argument("--no-fullstack", action="store_true", help="Start only the dashboard.")
    args = parser.parse_args()

    log("╔" + "═" * 58 + "╗")
    log("║  LARRY G-FORCE — SYSTEM LAUNCHER")
    log("╚" + "═" * 58 + "╝")

    # Refuse to run a second copy: one launcher = one stack = one Telegram bot.
    if not _acquire_singleton():
        log("Another start_system launcher is already running — exiting this one "
            "(prevents duplicate Telegram bots and extra browser tabs).", "WARN")
        return 0

    _enter_kill_on_close_job()
    if not IS_WINDOWS:
        try:
            os.setpgrp()
        except Exception:
            pass
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    py = _python()
    host, port = _dashboard_hostport()

    # 1) Dashboard
    started_dashboard = False
    if _port_open(host, port):
        log(f"Dashboard already listening on {host}:{port} — not starting another.")
    elif DASHBOARD.exists():
        # --no-browser: THIS launcher owns opening the single browser tab (step 3),
        # so the dashboard must not also pop its own — that was one of the 3 tabs.
        _spawn("dashboard", [py, str(DASHBOARD), "--no-browser"], ROOT, "dashboard.log")
        started_dashboard = True
        log(f"Waiting for dashboard on {host}:{port} ...")
        for _ in range(40):
            if _port_open(host, port):
                break
            time.sleep(0.5)
        log("Dashboard is up." if _port_open(host, port) else "Dashboard not reachable yet (continuing).", )
    else:
        log(f"dashboard_hub.py not found at {DASHBOARD}", "WARN")

    # 2) Full stack (venv/deps/config + Ollama fast model + Telegram bot)
    if args.no_fullstack:
        log("Full stack skipped (--no-fullstack).")
    elif FULLSTACK.exists():
        _spawn("fullstack", [py, str(FULLSTACK)], FULLSTACK.parent, "larry_fullstack.log")
    else:
        log(f"start_fullstack.py not found at {FULLSTACK}", "WARN")

    # 3) Open the dashboard — exactly ONE tab, and only if THIS launcher started
    # it. Re-running against an already-up dashboard won't pop another tab.
    if not args.no_browser and started_dashboard and _port_open(host, port):
        url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
        log(f"Opening {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass

    log("=" * 60)
    log("System is up. Supervising — Ctrl+C (or kill this process) shuts everything down.")
    log("=" * 60)

    try:
        while not _stop:
            # If every child has exited, there's nothing left to supervise.
            if _children and all(c["proc"].poll() is not None for c in _children):
                log("All child processes have exited.", "WARN")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        teardown()
    log("System launcher stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
