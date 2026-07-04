#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — FULL STACK LAUNCHER                                ║
║   venv · deps · config · Ollama (fast tool model) · Telegram bot     ║
╚══════════════════════════════════════════════════════════════════════╝

One entry point that brings up the entire local Larry stack. It is registered
in dashboard_hub.py as the "Larry Full Stack" service, and can also be run
directly in a console:

    python launchers/start_fullstack.py            # full bring-up
    python launchers/start_fullstack.py --setup    # force venv + pip install
    python launchers/start_fullstack.py --no-telegram
    python launchers/start_fullstack.py --no-ollama

Bring-up order
--------------
  1. Ensure .venv exists and dependencies are installed (idempotent — a marker
     file skips re-installing on every launch; --setup forces it).
  2. Load + validate larry_config.json  (the "fullstack" block tunes this).
  3. Start `ollama serve` if it is not already up, then ensure the fast tool
     model (Larry-Fast-9b) is built and warm-loaded into VRAM.
  4. Start the Telegram bot (src/telegram_bot.py); it reads TELEGRAM_BOT_TOKEN
     from .env via python-dotenv.

This process then SUPERVISES: it blocks until interrupted (Ctrl+C, SIGTERM, or
the dashboard's Stop button) and tears down the children it started.

Dual-boot aware: this PC runs both Windows and Linux. On Windows the children
are placed in a kill-on-close Job Object so that a hard terminate from the
dashboard also kills the Telegram bot. On Linux we use a process group +
signal handlers.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import shutil
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# Make box-drawing / emoji in our logs safe under a cp1252 console or piped
# stdout (pythonw, Scheduled Task, PowerShell capture). Imported by every
# launcher, so this covers start_system.py and setup_larry_version.py too.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# launchers/ -> project root (the folder that holds agent_v2.py, larry_config.json)
ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
DEPS_MARKER = VENV / ".larry_deps_ok"
REQUIREMENTS = ROOT / "requirements.txt"
CONFIG_PATH = ROOT / "larry_config.json"
TELEGRAM_SCRIPT = ROOT / "src" / "telegram_bot.py"
LOG_DIR = ROOT / "logs"

# Children we started, for teardown. Each: {"name", "proc", "kind"}.
_children: list[dict] = []
_stop = False
_win_job = None  # keep the Windows Job Object handle alive for the process lifetime


# ── logging ──────────────────────────────────────────────────────────────────
def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {level:<5} {msg}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


# The agent's heavy deps may live in the system Python rather than the .venv.
# We pick whichever interpreter can actually import them to run the children.
_DEPS_PROBE = ("import importlib.util as u,sys; "
               "sys.exit(0 if (u.find_spec('langchain_ollama') and u.find_spec('chromadb')) else 1)")


def _has_deps(exe: str) -> bool:
    try:
        return subprocess.run([exe, "-c", _DEPS_PROBE],
                              capture_output=True, timeout=25).returncode == 0
    except Exception:
        return False


def best_python() -> str:
    """Interpreter that has the agent's heavy deps (langchain_ollama, chromadb).
    Probes the .venv, this process's python, and python/python3 on PATH; falls
    back to the .venv interpreter if none qualify (setup will populate it)."""
    seen: set[str] = set()
    candidates: list[str] = []
    for c in (venv_python(), Path(sys.executable),
              shutil.which("python"), shutil.which("python3")):
        if c and str(c) not in seen:
            seen.add(str(c))
            candidates.append(str(c))
    for exe in candidates:
        if _has_deps(exe):
            return exe
    vp = venv_python()
    return str(vp) if vp.exists() else sys.executable


# ── Windows kill-on-close Job Object ─────────────────────────────────────────
def _enter_kill_on_close_job() -> None:
    """
    Put THIS process into a Job Object with KILL_ON_JOB_CLOSE. Children spawned
    afterwards inherit the job, so when this launcher dies (even via the
    dashboard's TerminateProcess), Windows kills the whole tree — no orphaned
    Telegram bot. No-op on non-Windows.
    """
    global _win_job
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        from ctypes import wintypes

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                        ("WriteOperationCount", ctypes.c_uint64),
                        ("OtherOperationCount", ctypes.c_uint64),
                        ("ReadTransferCount", ctypes.c_uint64),
                        ("WriteTransferCount", ctypes.c_uint64),
                        ("OtherTransferCount", ctypes.c_uint64)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info)
        ):
            return
        kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
        _win_job = job  # MUST stay referenced; closing the handle kills the job
        log("Windows Job Object active (children die with this launcher).")
    except Exception as e:
        log(f"Could not create Job Object ({e}); children may outlive a hard kill.", "WARN")


# ── step 1: venv + dependencies ──────────────────────────────────────────────
def ensure_venv_and_deps(force: bool, install_deps: bool) -> str:
    """Return the interpreter to run children with. Prefer one that already has
    the heavy deps; otherwise create/populate the .venv and use that."""
    log("Step 2/4 — interpreter + dependencies")
    chosen = best_python()
    if not force and _has_deps(chosen):
        log(f"Using interpreter with deps already present: {chosen}")
        return chosen

    py = venv_python()
    if not py.exists():
        log(f"Creating virtual environment at {VENV} ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    else:
        log(f"venv present: {VENV}")

    if not install_deps:
        log("Dependency install disabled by config — skipping pip.", "WARN")
        return str(py)

    if force or not DEPS_MARKER.exists() or not _has_deps(str(py)):
        if not REQUIREMENTS.exists():
            log(f"requirements.txt not found at {REQUIREMENTS} — skipping pip.", "WARN")
        else:
            log("Installing dependencies into .venv (can take a few minutes) ...")
            subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip", "-q"])
            subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(REQUIREMENTS), "-q"])
            DEPS_MARKER.write_text(datetime.now().isoformat(), encoding="utf-8")
            log("Dependencies installed.")
    else:
        log("Dependencies already installed (marker present). Use --setup to force.")
    return str(py)


# ── step 2: config ───────────────────────────────────────────────────────────
def load_config() -> dict:
    log("Step 1/4 — load config")
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        log(f"Loaded {CONFIG_PATH.name} (agent={cfg.get('agent_name','?')}, "
            f"version={cfg.get('version','?')})")
        return cfg
    except Exception as e:
        log(f"Could not read {CONFIG_PATH.name} ({e}); using defaults.", "WARN")
        return {}


# ── step 3: ollama + fast tool model ─────────────────────────────────────────
def _ollama_host(cfg: dict) -> str:
    return (cfg.get("ollama", {}) or {}).get("host", "http://localhost:11434").rstrip("/")


def _ollama_up(host: str) -> bool:
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_tags(host: str) -> list[str]:
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if IS_WINDOWS:
        guess = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if guess.exists():
            return str(guess)
    return None


def start_ollama(cfg: dict) -> None:
    log("Step 3/4 — Ollama + fast tool model")
    fs = cfg.get("fullstack", {}) or {}
    host = _ollama_host(cfg)

    if not fs.get("start_ollama", True):
        log("start_ollama disabled by config — skipping Ollama bring-up.")
        return

    if _ollama_up(host):
        log(f"Ollama already serving at {host}.")
    else:
        exe = _ollama_exe()
        if not exe:
            log("ollama executable not found on PATH — cannot start server.", "WARN")
            return
        log(f"Starting `ollama serve` ({exe}) ...")
        # Inherit env; ollama serve binds 127.0.0.1:11434 by default.
        proc = subprocess.Popen([exe, "serve"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _children.append({"name": "ollama serve", "proc": proc, "kind": "ollama"})
        # Wait for it to come up.
        for _ in range(30):
            if _ollama_up(host):
                break
            time.sleep(1)
        if _ollama_up(host):
            log(f"Ollama is up at {host}.")
        else:
            log("Ollama did not become ready within 30s.", "WARN")
            return

    _ensure_fast_model(cfg, host)


def _ensure_fast_model(cfg: dict, host: str) -> None:
    fs = cfg.get("fullstack", {}) or {}
    model = fs.get("fast_tool_model", "qwen2.5:7b-instruct")
    mf_rel = (fs.get("fast_tool_modelfile") or "").strip()
    modelfile = (ROOT / mf_rel) if mf_rel else None
    fallback = (cfg.get("profiles", {}) or {}).get("fast_model", "ministral-3:latest")
    keep_alive = (cfg.get("ollama", {}) or {}).get("keep_alive", "10m")
    exe = _ollama_exe()
    if not exe:
        log("ollama executable not found — cannot ensure the fast tool model.", "WARN")
        return

    def have_model(name: str) -> bool:
        return any(t == name or t.split(":")[0] == name.split(":")[0]
                   for t in _ollama_tags(host))

    if have_model(model):
        log(f"Fast tool model '{model}' already present.")
    elif modelfile and modelfile.is_file():
        # Custom model defined by a Modelfile -> build it locally.
        log(f"Building '{model}' from {modelfile.name} (first run can be slow) ...")
        try:
            subprocess.check_call([exe, "create", model, "-f", str(modelfile)])
            log(f"Model '{model}' built.")
        except Exception as e:
            log(f"`ollama create {model}` failed ({e}); trying to pull '{fallback}'.", "WARN")
            model = fallback
    else:
        # Plain registry model -> pull it (downloads on first run).
        log(f"Fast tool model '{model}' not found locally — pulling it (first run downloads it) ...")
        try:
            subprocess.check_call([exe, "pull", model])
            log(f"Pulled '{model}'.")
        except Exception as e:
            log(f"`ollama pull {model}` failed ({e}); falling back to '{fallback}'.", "WARN")
            model = fallback

    # Make sure SOMETHING fast is available before we try to warm it.
    if not have_model(model):
        log(f"Pulling fallback fast model '{model}' ...")
        try:
            subprocess.check_call([exe, "pull", model])
        except Exception as e:
            log(f"`ollama pull {model}` failed ({e}); no fast model available.", "WARN")
            return

    # Warm-load into VRAM (empty prompt loads the model without generating).
    try:
        payload = json.dumps({"model": model, "prompt": "", "keep_alive": keep_alive}).encode()
        req = urllib.request.Request(host + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120):
            pass
        log(f"Warm-loaded '{model}' (keep_alive={keep_alive}).")
    except Exception as e:
        log(f"Warm-load of '{model}' skipped ({e}).", "WARN")


# ── step 4: telegram bot ─────────────────────────────────────────────────────
def start_telegram(cfg: dict, py: Path) -> None:
    log("Step 4/4 — Telegram bot")
    fs = cfg.get("fullstack", {}) or {}
    if not fs.get("start_telegram", True):
        log("start_telegram disabled by config — skipping bot.")
        return
    if not cfg.get("features", {}).get("telegram_enabled", True):
        log("features.telegram_enabled is false — skipping bot.")
        return
    if not TELEGRAM_SCRIPT.exists():
        log(f"Telegram script not found at {TELEGRAM_SCRIPT} — skipping.", "WARN")
        return
    if not os.getenv("TELEGRAM_BOT_TOKEN") and not (ROOT / ".env").exists():
        log("No TELEGRAM_BOT_TOKEN in env and no .env file — bot will likely fail to start.", "WARN")

    log(f"Launching {TELEGRAM_SCRIPT.relative_to(ROOT)} ...")
    # cwd=ROOT so python-dotenv finds .env and relative paths resolve.
    proc = subprocess.Popen([str(py), str(TELEGRAM_SCRIPT)], cwd=str(ROOT))
    _children.append({"name": "telegram_bot", "proc": proc, "kind": "telegram"})
    log(f"Telegram bot started (PID {proc.pid}).")


# ── supervise + teardown ─────────────────────────────────────────────────────
def teardown(stop_ollama: bool) -> None:
    for child in reversed(_children):
        proc = child["proc"]
        if proc.poll() is not None:
            continue
        if child["kind"] == "ollama" and not stop_ollama:
            log("Leaving `ollama serve` running (shared by other services). "
                "Use --stop-ollama-on-exit to change.")
            continue
        log(f"Stopping {child['name']} (PID {proc.pid}) ...")
        try:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as e:
            log(f"Error stopping {child['name']}: {e}", "WARN")


def _signal_handler(signum, frame):
    global _stop
    _stop = True


def supervise(stop_ollama: bool) -> int:
    # Identify the telegram child as the "main" process to watch, if present.
    main = next((c for c in _children if c["kind"] == "telegram"), None)
    log("=" * 60)
    log("Full stack is up. Supervising — Ctrl+C (or dashboard Stop) to shut down.")
    log("=" * 60)
    try:
        while not _stop:
            if main and main["proc"].poll() is not None:
                code = main["proc"].returncode
                log(f"Telegram bot exited (code {code}). Shutting down stack.", "WARN")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        teardown(stop_ollama)
    log("Full stack stopped.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Larry G-Force full stack launcher.")
    parser.add_argument("--setup", action="store_true",
                        help="Force venv creation + pip install -r requirements.txt.")
    parser.add_argument("--no-ollama", action="store_true", help="Do not start Ollama.")
    parser.add_argument("--no-telegram", action="store_true", help="Do not start the Telegram bot.")
    parser.add_argument("--stop-ollama-on-exit", action="store_true",
                        help="Also stop the Ollama server we started on shutdown.")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("╔" + "═" * 58 + "╗")
    log("║  LARRY G-FORCE — FULL STACK LAUNCHER")
    log("╚" + "═" * 58 + "╝")

    _enter_kill_on_close_job()
    if not IS_WINDOWS:
        try:
            os.setpgrp()
        except Exception:
            pass
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    cfg = {}
    try:
        cfg = load_config()
        # Config first so the fullstack block can toggle dependency install.
        fs = cfg.get("fullstack", {}) or {}
        py = ensure_venv_and_deps(force=args.setup, install_deps=fs.get("install_deps", True))

        if args.no_ollama:
            log("Ollama bring-up skipped (--no-ollama).")
        else:
            start_ollama(cfg)

        if args.no_telegram:
            log("Telegram bot skipped (--no-telegram).")
        else:
            start_telegram(cfg, py)
    except subprocess.CalledProcessError as e:
        log(f"A setup step failed: {e}", "ERROR")
        teardown(args.stop_ollama_on_exit)
        return 1
    except Exception as e:
        log(f"Unexpected error during bring-up: {e}", "ERROR")
        teardown(args.stop_ollama_on_exit)
        return 1

    return supervise(args.stop_ollama_on_exit)


if __name__ == "__main__":
    sys.exit(main())
