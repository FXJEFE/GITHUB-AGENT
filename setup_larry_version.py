#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — SETUP (this version)                              ║
║   Reproduce/prepare the exact working configuration.                ║
╚══════════════════════════════════════════════════════════════════════╝

Run from the dashboard (Services → "Setup (this version)") or directly:

    python launchers/setup_larry_version.py
    python launchers/setup_larry_version.py --force      # rebuild venv + reinstall deps
    python launchers/setup_larry_version.py --no-ollama  # skip model pull

What it does
------------
  1. Selects the interpreter that has the agent deps (or builds the .venv and
     installs requirements into it).
  2. Ensures Ollama is up and the default tool model (qwen3:8b) is pulled+warm.
  3. Validates the files this version needs (config, mcp.json, .env, prompt).
  4. Writes VERSION_STATE.json — a snapshot of THIS exact setup (interpreter,
     model, ports, and where all state is saved).

It changes nothing destructive: it installs/pulls what's missing and records
the result.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Reuse the full-stack launcher's helpers (interpreter detection, ollama, etc.)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from start_fullstack import (  # noqa: E402
    ROOT, VENV, CONFIG_PATH, log, load_config,
    ensure_venv_and_deps, best_python, start_ollama,
)

VERSION_STATE = ROOT / "VERSION_STATE.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Set up / snapshot this exact Larry version.")
    ap.add_argument("--force", action="store_true", help="Force venv build + reinstall deps.")
    ap.add_argument("--no-ollama", action="store_true", help="Skip Ollama + model pull.")
    args = ap.parse_args()

    log("╔" + "═" * 58 + "╗")
    log("║  LARRY G-FORCE — SETUP (this version)")
    log("╚" + "═" * 58 + "╝")

    # 1) Config + interpreter + deps
    cfg = load_config()
    fs = cfg.get("fullstack", {}) or {}
    interpreter = ensure_venv_and_deps(force=args.force,
                                       install_deps=fs.get("install_deps", True))

    # 2) Validate the files this version needs
    log("Step 3/4 — validate files")
    checks = {
        "larry_config.json": CONFIG_PATH,
        "mcp.json":          ROOT / "mcp.json",
        ".env (secrets)":    ROOT / ".env",
        "system prompt":     ROOT / "prompts" / "LARRY_SYSTEM_PROMPT.md",
    }
    file_state = {}
    for label, path in checks.items():
        ok = path.exists()
        file_state[label] = {"path": str(path), "present": ok}
        log(f"  {'OK ' if ok else 'MISSING'} {label}: {path}", "INFO" if ok else "WARN")

    # 3) Ollama + default tool model
    model = cfg.get("ollama", {}).get("default_model", "qwen3:8b")
    if args.no_ollama:
        log("Step 4/4 — Ollama skipped (--no-ollama)")
    else:
        start_ollama(cfg)  # ensures server up + pulls/warms the fast tool model

    # 4) Snapshot this exact version
    snapshot = {
        "captured": datetime.now().isoformat(timespec="seconds"),
        "agent_name": cfg.get("agent_name"),
        "config_version": cfg.get("version"),
        "interpreter": interpreter,
        "venv": str(VENV),
        "default_model": model,
        "fast_tool_model": fs.get("fast_tool_model"),
        "ollama_host": cfg.get("ollama", {}).get("host"),
        "dashboard_port": (cfg.get("dashboard", {}) or {}).get("port", 3777),
        "files": file_state,
        "state_locations": {
            "config":         str(CONFIG_PATH),
            "mcp":            str(ROOT / "mcp.json"),
            "secrets":        str(ROOT / ".env"),
            "agent_status":   str(ROOT / "logs" / "agent_status.json"),
            "memory":         [str(ROOT / "memory.json"),
                               str(ROOT / "data" / "larry_memory.json")],
            "conversation":   str(ROOT / "data" / "conversation_history.json"),
            "context_db":     str(ROOT / "data" / "unified_context.db"),
            "rag_chroma":     str(ROOT / "chroma_db"),
            "dashboard_auth": str(ROOT / "db" / "dashboard_auth.json"),
            "saved_db":       str(ROOT / "db"),
            "logs":           str(ROOT / "logs"),
        },
    }
    VERSION_STATE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    log("=" * 60)
    log(f"Setup complete. Snapshot: {VERSION_STATE}")
    log(f"  interpreter   : {interpreter}")
    log(f"  default model : {model}")
    log("Start everything from the dashboard Services tab -> 'Startup (full system)',")
    log("or run:  python launchers/start_system.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
