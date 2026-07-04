#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — MASTER ORCHESTRATOR  (single A–Z login entry point)     ║
╚══════════════════════════════════════════════════════════════════════════╝

ONE file that brings up the whole stack, in resource-tiered order so login stays
light and VRAM/CPU stay free until actually needed:

  Tier 0  (instant, near-zero resource — the control plane):
    • load configs (larry_config.json + src/config)
    • set low-VRAM Ollama env (NUM_PARALLEL=1, MAX_LOADED_MODELS=1, keep_alive)
    • boot + hold the kali-linux WSL2 distro (managed `sleep infinity` holder)
    • ensure `ollama serve` is up — WITHOUT preloading any model
    • start the dashboard (dashboard_hub_v2.py) — the web control plane
    • start the resource governor (risk management: VRAM/CPU/RAM ceilings)
    • open exactly ONE browser tab to the dashboard

  Tier 1  (deferred by startup_delay_seconds — the workers/clients):
    • full stack (Telegram bot) via start_fullstack.py --no-ollama
      (no model is warm-loaded at startup; models load lazily on first use)
    • optional: MCP tool preload, HTTP API (:7333), docker compose

It then SUPERVISES everything. On Windows all children live in a kill-on-close
Job Object, so killing this one process tears the whole stack down — no orphans,
no duplicate Telegram bots, no duplicate dashboards.

Run:
    python launchers/larry_orchestrator.py                 # full tiered bring-up
    python launchers/larry_orchestrator.py --status        # one-shot health, no side effects
    python launchers/larry_orchestrator.py --minimal       # Tier 0 only (control plane)
    python launchers/larry_orchestrator.py --with-api --with-docker
    python launchers/larry_orchestrator.py --no-browser

Optional larry_config.json block (all keys optional; defaults shown):
    "orchestrator": {
        "startup_delay_seconds": 8,   # delay before Tier 1 (keeps login light)
        "warm_fast_model": false,     # true = warm the fast model at boot (more VRAM)
        "start_governor": true,
        "start_api": false,
        "start_docker": false,
        "preload_mcp": false,
        "open_browser": true,
        "wsl_distro": "kali-linux"
    }
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

# Locate the GITHUB root + launchers/ dir regardless of where THIS file lives
# (it may sit in launchers/ or have been copied to the repo root). We anchor on
# launchers/start_fullstack.py so paths and imports stay correct either way.
def _find_launchers() -> Path:
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        cand = base / "start_fullstack.py"
        if cand.exists():                       # we're inside launchers/
            return base
        cand = base / "launchers" / "start_fullstack.py"
        if cand.exists():                       # we're above launchers/ (repo root)
            return base / "launchers"
    # last resort: assume sibling layout (original behaviour)
    return here.parent

LAUNCHERS = _find_launchers()

# launchers/ is importable so we reuse the full-stack launcher's battle-tested
# helpers (best interpreter, Windows Job Object, Ollama probes) instead of
# duplicating them.
sys.path.insert(0, str(LAUNCHERS))
try:
    from start_fullstack import (  # noqa: E402
        best_python, _enter_kill_on_close_job, _ollama_up, _ollama_exe, _ollama_host,
    )
    HELPERS_SOURCE = "start_fullstack.py"
except ImportError:
    # ── standalone fallbacks (FIX: previously a hard ImportError crash) ────
    # start_fullstack.py not found next to us. Provide minimal, stdlib-only
    # versions of its helpers so the orchestrator still brings the stack up.
    # The start_fullstack versions always win when the file is present.
    import shutil as _shutil
    import urllib.request as _urlreq

    HELPERS_SOURCE = "LOCAL FALLBACKS (start_fullstack.py NOT found)"

    def best_python() -> str:
        """Prefer this repo's venv interpreter; else the one running us."""
        root = LAUNCHERS.parent
        sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
        for venv in (".venv", "venv", "env"):
            cand = root / venv / sub[0] / sub[1]
            if cand.exists():
                return str(cand)
        return sys.executable

    def _enter_kill_on_close_job() -> None:
        """Windows Job Object, kill-on-close. Best effort; no-op elsewhere."""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32

            class _BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _IO(ctypes.Structure):
                _fields_ = [(n, ctypes.c_ulonglong) for n in
                            ("ReadOperationCount", "WriteOperationCount",
                             "OtherOperationCount", "ReadTransferCount",
                             "WriteTransferCount", "OtherTransferCount")]

            class _EXT(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _BASIC),
                            ("IoInfo", _IO),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            job = k32.CreateJobObjectW(None, None)
            if not job:
                return
            info = _EXT()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            k32.SetInformationJobObject(job, 9,  # ExtendedLimitInformation
                                        ctypes.byref(info), ctypes.sizeof(info))
            k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())
        except Exception:
            pass

    def _ollama_host(cfg: dict) -> str:
        o = cfg.get("ollama", {}) or {}
        host = o.get("host") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        if not host.startswith("http"):
            host = "http://" + host
        return host.rstrip("/")

    def _ollama_up(host: str) -> bool:
        try:
            with _urlreq.urlopen(host + "/api/version", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _ollama_exe():
        exe = _shutil.which("ollama")
        if exe:
            return exe
        if os.name == "nt":
            for cand in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                         Path("C:/Program Files/Ollama/ollama.exe")):
                if cand.exists():
                    return str(cand)
        return None

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

ROOT = LAUNCHERS.parent                                 # GITHUB/
SRC = ROOT / "src"
DASHBOARD = ROOT / "dashboard_hub_v2.py"
FULLSTACK = ROOT / "launchers" / "start_fullstack.py"
GOVERNOR = SRC / "resource_governor.py"
AGENT_CLI = SRC / "agent_v2.py"                          # interactive agent (real, src copy)
MCP_HOST_SERVERS = ROOT / "mcp_host" / "servers.json"   # agentic MCP toolset
CONFIG_PATH = ROOT / "larry_config.json"
LOG_DIR = ROOT / "logs"
LOCK_FILE = LOG_DIR / ".larry_orchestrator.lock"

_children: list[dict] = []
_stop = False


# ── logging ───────────────────────────────────────────────────────────────
def log(msg: str, level: str = "INFO") -> None:
    print(f"[{datetime.now():%H:%M:%S}] {level:<5} {msg}", flush=True)


# ── config ────────────────────────────────────────────────────────────────
def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"Could not read {CONFIG_PATH.name} ({e}); using defaults.", "WARN")
        return {}


def orch_opt(cfg: dict, key: str, default):
    return (cfg.get("orchestrator", {}) or {}).get(key, default)


def dashboard_hostport(cfg: dict) -> tuple[str, int]:
    d = cfg.get("dashboard", {}) or {}
    host = d.get("host", "127.0.0.1")
    return ("127.0.0.1" if host in ("0.0.0.0", "") else host), int(d.get("port", 3777))


# ── single-instance lock ────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=5)
            return str(pid) in out.stdout
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_singleton() -> bool:
    """One orchestrator = one stack. Prevents the duplicate Telegram bots /
    duplicate dashboards / duplicate login prompts caused by two launchers."""
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


# ── process helpers ─────────────────────────────────────────────────────────
def _port_open(host: str, port: int) -> bool:
    host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _spawn(name: str, argv: list[str], cwd: Path, logfile: str, hidden: bool = False) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOG_DIR / logfile, "a", encoding="utf-8")
    fh.write(f"\n===== {name} started {datetime.now().isoformat()} =====\n")
    fh.flush()
    flags = CREATE_NO_WINDOW if hidden else 0
    proc = subprocess.Popen(argv, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT,
                            creationflags=flags)
    _children.append({"name": name, "proc": proc, "log": fh})
    log(f"Started {name} (PID {proc.pid}) -> logs/{logfile}")


# ── Tier 0: control plane ───────────────────────────────────────────────────
def set_low_resource_env(cfg: dict) -> None:
    """Tune Ollama concurrency. `max_loaded_models` lets several models stay
    co-resident (e.g. chat LLM + embedding model + a chunking/reranking model)
    so RAG/embeddings don't evict the chat model and thrash on every request.
    Small embed models (~0.3-0.7GB) coexist with one big chat model on 8GB
    VRAM; Ollama spills overflow layers to CPU/DDR5. Override in larry_config
    ollama.{max_loaded_models,num_parallel,keep_alive}."""
    o = cfg.get("ollama", {}) or {}
    keep_alive = o.get("keep_alive", "30m")
    num_parallel = str(o.get("num_parallel", 1))
    max_loaded = str(o.get("max_loaded_models", 3))   # 3+ models loaded at once
    os.environ.setdefault("OLLAMA_NUM_PARALLEL", num_parallel)
    os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", max_loaded)
    os.environ.setdefault("OLLAMA_KEEP_ALIVE", keep_alive)
    log(f"Ollama env: NUM_PARALLEL={num_parallel} MAX_LOADED_MODELS={max_loaded} "
        f"KEEP_ALIVE={keep_alive}")


def start_wsl_keepalive(cfg: dict) -> None:
    distro = orch_opt(cfg, "wsl_distro", "kali-linux")
    if not IS_WINDOWS:
        return
    try:
        have = subprocess.run(["wsl", "-l", "-q"], capture_output=True, text=True,
                              timeout=10, encoding="utf-16-le")
        if distro not in (have.stdout or ""):
            # try utf-8 fallback (wsl output encoding varies)
            have = subprocess.run(["wsl", "-l", "-q"], capture_output=True, text=True, timeout=10)
        if distro not in (have.stdout or ""):
            log(f"WSL distro '{distro}' not found — skipping keepalive.", "WARN")
            return
    except Exception as e:
        log(f"WSL not available ({e}) — skipping keepalive.", "WARN")
        return
    # Managed foreground holder: an active `sleep infinity` keeps WSL2 from
    # idle-shutting-down the distro. In the Job Object, so it dies with us.
    proc = subprocess.Popen(["wsl", "-d", distro, "--", "sleep", "infinity"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)
    _children.append({"name": f"wsl-keepalive[{distro}]", "proc": proc, "log": None})
    log(f"WSL2 '{distro}' booted + held (PID {proc.pid}).")


def ensure_ollama(cfg: dict) -> None:
    host = _ollama_host(cfg)
    if _ollama_up(host):
        log(f"Ollama already serving at {host}.")
        log("   (pre-existing server — the OLLAMA_* env set above does NOT "
            "apply to it; only Windows user env vars do)")
        return
    exe = _ollama_exe()
    if not exe:
        log("ollama executable not found on PATH — cannot start server.", "WARN")
        return
    log("Starting `ollama serve` (no model preloaded — low resource) ...")
    proc = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    _children.append({"name": "ollama serve", "proc": proc, "log": None})
    for _ in range(30):
        if _ollama_up(host):
            break
        time.sleep(1)
    log("Ollama is up." if _ollama_up(host) else "Ollama not ready within 30s.")


def start_dashboard(cfg: dict, py: str) -> bool:
    host, port = dashboard_hostport(cfg)
    if _port_open(host, port):
        log(f"Dashboard already on {host}:{port} — not starting another.")
        return False
    if not DASHBOARD.exists():
        log(f"{DASHBOARD.name} not found at {DASHBOARD}", "WARN")
        return False
    _spawn("dashboard", [py, str(DASHBOARD), "--no-browser"], ROOT, "dashboard.log")
    for _ in range(40):
        if _port_open(host, port):
            break
        time.sleep(0.5)
    return _port_open(host, port)


def start_governor(cfg: dict, py: str) -> None:
    if not orch_opt(cfg, "start_governor", True):
        log("Resource governor disabled by config.")
        return
    if not GOVERNOR.exists():
        log(f"resource_governor.py not found at {GOVERNOR}", "WARN")
        return
    _spawn("governor", [py, str(GOVERNOR)], SRC, "governor.log")


def open_browser_once(cfg: dict, started_dashboard: bool, no_browser: bool) -> None:
    if no_browser or not orch_opt(cfg, "open_browser", True):
        return
    host, port = dashboard_hostport(cfg)
    if started_dashboard and _port_open(host, port):
        url = f"http://{host}:{port}"
        log(f"Opening {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass


# ── Tier 1: workers / clients ───────────────────────────────────────────────
def start_fullstack(cfg: dict, py: str) -> None:
    if not FULLSTACK.exists():
        log(f"start_fullstack.py not found at {FULLSTACK}", "WARN")
        return
    argv = [py, str(FULLSTACK)]
    if not orch_opt(cfg, "warm_fast_model", False):
        # Ollama is already serving (Tier 0); --no-ollama means the full stack
        # only starts the Telegram bot and does NOT warm-load a model -> the
        # lowest-resource startup. Models load lazily on the first message.
        argv.append("--no-ollama")
    _spawn("fullstack", argv, FULLSTACK.parent, "larry_fullstack.log")


def _report_mcp_host_servers() -> None:
    """Surface the agentic MCP toolset (mcp_host/servers.json) — the tools the
    agent / Telegram bot expose via "agent search": filesystem, fetch (web
    scrape), rag, youtube, shell (CLI exec), etc. They start lazily inside the
    agent/bot's background MCP host; this just shows the chain is wired."""
    if not MCP_HOST_SERVERS.exists():
        log(f"mcp_host servers.json not found at {MCP_HOST_SERVERS} — agentic MCP "
            f"tools unavailable.", "WARN")
        return
    try:
        data = json.loads(MCP_HOST_SERVERS.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        enabled = [n for n, s in servers.items() if s.get("enabled", True)]
        disabled = [n for n in servers if n not in enabled]
        log(f"Agentic MCP host: {len(enabled)} server(s) wired -> {', '.join(enabled)}"
            + (f"  (disabled: {', '.join(disabled)})" if disabled else ""))
        log("   start lazily inside the agent / Telegram bot background MCP host")
    except Exception as e:
        log(f"Could not parse mcp_host/servers.json ({e}).", "WARN")


def start_agent_cli(cfg: dict, py: str) -> None:
    """Launch the real interactive agent (src/agent_v2.py) in its OWN console
    window so it stays usable as a REPL. It boots its own background MCP host
    (the agentic toolset reported above). Toggle with
    orchestrator.start_agent_cli=false."""
    if not orch_opt(cfg, "start_agent_cli", True):
        log("Interactive agent CLI disabled (orchestrator.start_agent_cli=false).")
        return
    if not AGENT_CLI.exists():
        log(f"agent_v2.py not found at {AGENT_CLI} — cannot start agent CLI.", "WARN")
        return
    # cwd=SRC so the script dir is on sys.path (mcp_supervisor, model_router, …)
    # and src-relative resources resolve exactly as in a manual run.
    flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0
    try:
        proc = subprocess.Popen([py, str(AGENT_CLI)], cwd=str(SRC), creationflags=flags)
        _children.append({"name": "agent_cli", "proc": proc, "log": None})
        log(f"Started interactive agent CLI (PID {proc.pid})"
            + (" in its own console." if IS_WINDOWS else "."))
    except Exception as e:
        log(f"Could not start agent CLI ({e}).", "WARN")


def preload_mcp(cfg: dict) -> None:
    # Always report the agentic MCP toolset so the orchestrator log shows it is
    # linked, regardless of the (legacy) preload_mcp toggle below.
    _report_mcp_host_servers()

    if not orch_opt(cfg, "preload_mcp", False):
        return
    if not cfg.get("features", {}).get("mcp_enabled", False):
        log("MCP disabled in features — skipping preload.")
        return
    mcp_path = ROOT / (cfg.get("mcp", {}).get("config_path", "./mcp.json").lstrip("./"))
    if not mcp_path.exists():
        log(f"MCP config not found at {mcp_path} — skipping.", "WARN")
        return
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", data.get("servers", {}))
        log(f"MCP config loaded: {len(servers)} tool server(s) registered "
            f"({', '.join(list(servers)[:6])}).")
    except Exception as e:
        log(f"Could not parse MCP config ({e}).", "WARN")


def start_api(cfg: dict, py: str, force: bool) -> None:
    if not (force or orch_opt(cfg, "start_api", False)):
        return
    main_py = SRC / "main.py"
    if not main_py.exists():
        log(f"src/main.py not found — cannot start API.", "WARN")
        return
    _spawn("api-server", [py, str(main_py), "serve"], SRC, "api_server.log")


def start_docker(cfg: dict, force: bool) -> None:
    if not (force or orch_opt(cfg, "start_docker", False)):
        return
    import shutil
    if not shutil.which("docker"):
        log("docker not on PATH — skipping docker bring-up.", "WARN")
        return
    compose = SRC / "docker-compose.yml"
    if not compose.exists():
        log("docker-compose.yml not found — skipping.", "WARN")
        return
    _spawn("docker-compose", ["docker", "compose", "-f", str(compose), "up", "-d"],
           SRC, "docker.log")


# ── supervise / teardown ─────────────────────────────────────────────────────
def teardown() -> None:
    for child in reversed(_children):
        proc = child["proc"]
        if proc.poll() is None:
            log(f"Stopping {child['name']} (PID {proc.pid}) ...")
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception as e:
                log(f"Error stopping {child['name']}: {e}", "WARN")
        if child.get("log"):
            try:
                child["log"].close()
            except Exception:
                pass


def _signal_handler(signum, frame):
    global _stop
    _stop = True


# ── tool-call self-test (one-shot, opt-in) ──────────────────────────────────
def selftest_tool_calling(cfg: dict, model: str) -> int:
    """POST /api/chat with a trivial tool schema (per docs.ollama.com →
    Tool calling) and verify the model returns a STRUCTURED
    message.tool_calls entry — not prose pretending it called a tool.

    This is the API-layer counterpart of the fabricated-tool-call problem:
    if this FAILS for a model, that model narrates tool use instead of
    emitting tool_calls, and the agent must not trust its "results".

    Opt-in via `--selftest-tools MODEL` because it warm-loads the model
    into VRAM (deliberately NOT part of the low-resource boot path).
    """
    import urllib.request
    host = _ollama_host(cfg)
    if not _ollama_up(host):
        log(f"Ollama not reachable at {host} — cannot run tool-call self-test.", "WARN")
        return 1
    payload = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "What is the temperature in Oslo? Use the tool."}],
        "stream": False,
        "tools": [{
            "type": "function",
            "function": {
                "name": "get_temperature",
                "description": "Get the current temperature for a city",
                "parameters": {
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {"type": "string",
                                 "description": "The name of the city"},
                    },
                },
            },
        }],
    }
    req = urllib.request.Request(
        host + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    log(f"Tool-call self-test: asking '{model}' to call get_temperature "
        "(this loads the model — may take a while on first run) ...")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"Self-test request failed: {e}", "WARN")
        return 1
    msg = data.get("message") or {}
    calls = msg.get("tool_calls") or []
    hits = [c for c in calls
            if (c.get("function") or {}).get("name") == "get_temperature"]
    if hits:
        args = (hits[0].get("function") or {}).get("arguments")
        log(f"PASS — '{model}' emitted a structured tool_call: "
            f"get_temperature({json.dumps(args, ensure_ascii=False)})")
        return 0
    log(f"FAIL — '{model}' returned NO structured tool_calls. "
        f"content={json.dumps(msg.get('content', ''), ensure_ascii=False)[:300]}", "WARN")
    return 1


# ── status (no side effects) ─────────────────────────────────────────────────
def print_status(cfg: dict) -> int:
    host, port = dashboard_hostport(cfg)
    ohost = _ollama_host(cfg)
    print("\n" + "=" * 56)
    print("  LARRY G-FORCE ORCHESTRATOR — STATUS")
    print("=" * 56)
    print(f"  config      : {CONFIG_PATH.name} (agent={cfg.get('agent_name','?')})")
    print(f"  ollama      : {ohost}  [{'UP' if _ollama_up(ohost) else 'down'}]")
    print(f"  dashboard   : http://{host}:{port}  [{'UP' if _port_open(host, port) else 'down'}]")
    if IS_WINDOWS:
        try:
            r = subprocess.run(["wsl", "-l", "-v"], capture_output=True, text=True,
                               timeout=10, encoding="utf-16-le")
            running = "kali" in (r.stdout or "").lower() and "Running" in (r.stdout or "")
            print(f"  wsl2 kali   : [{'running' if running else 'stopped/unknown'}]")
        except Exception:
            print("  wsl2 kali   : [unknown]")
    lock = "held" if LOCK_FILE.exists() else "free"
    print(f"  inst. lock  : {lock}")
    print("=" * 56 + "\n")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Larry G-Force master orchestrator.")
    parser.add_argument("--status", action="store_true", help="One-shot health, no side effects.")
    parser.add_argument("--minimal", action="store_true", help="Tier 0 only (control plane).")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-fullstack", action="store_true")
    parser.add_argument("--no-agent", action="store_true",
                        help="Do not launch the interactive agent CLI console.")
    parser.add_argument("--with-api", action="store_true")
    parser.add_argument("--with-docker", action="store_true")
    parser.add_argument("--selftest-tools", metavar="MODEL",
                        help="One-shot: verify MODEL emits structured tool_calls "
                             "via /api/chat (loads the model), then exit.")
    args = parser.parse_args()

    cfg = load_config()
    if args.status:
        return print_status(cfg)
    if args.selftest_tools:
        return selftest_tool_calling(cfg, args.selftest_tools)

    log("╔" + "═" * 56 + "╗")
    log("║  LARRY G-FORCE — MASTER ORCHESTRATOR")
    log("╚" + "═" * 56 + "╝")

    if not acquire_singleton():
        log("Another orchestrator is already running — exiting (prevents "
            "duplicate stacks, bots and dashboard logins).", "WARN")
        return 0

    _enter_kill_on_close_job()
    if not IS_WINDOWS:
        try:
            os.setpgrp()
        except Exception:
            pass
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    py = best_python()
    log(f"Interpreter: {py}")
    log(f"Helpers    : {HELPERS_SOURCE}")

    # ── Tier 0 — control plane (light) ──────────────────────────────────────
    log("── Tier 0: control plane ──")
    set_low_resource_env(cfg)
    start_wsl_keepalive(cfg)
    ensure_ollama(cfg)
    started_dashboard = start_dashboard(cfg, py)
    start_governor(cfg, py)
    open_browser_once(cfg, started_dashboard, args.no_browser)

    # ── Tier 1 — workers / clients (deferred to keep login light) ───────────
    if not args.minimal:
        delay = int(orch_opt(cfg, "startup_delay_seconds", 8))
        log(f"── Tier 1 in {delay}s: workers / clients ──")
        for _ in range(delay):
            if _stop:
                break
            time.sleep(1)
        if not _stop:
            preload_mcp(cfg)
            if not args.no_fullstack:
                start_fullstack(cfg, py)
            if not args.no_agent:
                start_agent_cli(cfg, py)
            start_api(cfg, py, args.with_api)
            start_docker(cfg, args.with_docker)
    else:
        log("Minimal mode — Tier 1 skipped.")

    log("=" * 58)
    log("System is up. Supervising — Ctrl+C / kill this process = full shutdown.")
    log("=" * 58)
    try:
        while not _stop:
            if _children and all(c["proc"].poll() is not None for c in _children):
                log("All child processes have exited.", "WARN")
                break
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        teardown()
    log("Orchestrator stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
