# agent_v2.py — final adjustments (tested patch, apply by hand)

Your `agent_v2.py` reached me as a chat document, not an uploaded file, so I did
NOT regenerate the whole ~1400-line file (retyping it risks silent drift, and I
won't hand you a "patched" copy I can't guarantee matches your original). Both
changes below were developed and tested in isolation — see the notes at the end.

If you'd rather I apply these directly and hand back a complete verified file,
upload `agent_v2.py` as an actual file and I'll patch + re-verify it.

---

## PATCH 1 — Harden the unguarded sibling imports (the real fix)

**Why:** these seven imports are currently unguarded AND run before `sys.path`
is set up. If any one module is missing/broken, the whole agent dies with a raw
traceback — and because the orchestrator launches it in its own console window,
that traceback can flash and vanish before you can read it.

### FIND (top of file — the contiguous block)

```python
from activity_stream import ActivityStream
from kali_tools import TOOLS, list_tools, tool_help, run_tool, parse_args_with_preset
import security_tools_installer  # canonical security tool installer (winget/choco)
from file_browser import FileBrowser, get_browser
from model_router import ModelRouter, TaskType, list_models, get_router, MODEL_CONFIGS
from memory_handoff import save_context_chunk, load_recent_handoffs, get_handoff_summary
```

### REPLACE WITH

```python
# ── Critical sibling imports (HARDENED) ──────────────────────────────────────
# These live next to this file in src/. Previously imported unguarded and BEFORE
# sys.path was set up, so any one missing/broken killed the whole agent with a
# raw traceback — which, launched in its own console by the orchestrator, could
# flash and vanish before it was readable. Now we (a) put this file's dir on
# sys.path FIRST, and (b) fail with a clear, persisted, pausing diagnostic.
import os as _os_boot, sys as _sys_boot
from pathlib import Path as _Path_boot


def _fatal_import(exc: Exception) -> None:
    here = _Path_boot(__file__).resolve().parent
    msg = (
        "\n" + "=" * 66 + "\n"
        "  LARRY G-FORCE — FATAL: a required sibling module failed to import\n"
        "  " + "-" * 62 + "\n"
        f"  {type(exc).__name__}: {exc}\n"
        f"  Searched in: {here}\n"
        "  Needed src/ siblings: activity_stream, kali_tools,\n"
        "  security_tools_installer, file_browser, model_router,\n"
        "  memory_handoff, persistence_logger.\n"
        "  Fix the module named above, then relaunch.\n"
        + "=" * 66 + "\n"
    )
    print(msg, flush=True)
    try:
        errlog = here / "logs" / "agent_startup_error.log"
        errlog.parent.mkdir(parents=True, exist_ok=True)
        import traceback as _tb
        with open(errlog, "a", encoding="utf-8") as fh:
            fh.write(msg)
            _tb.print_exc(file=fh)
    except Exception:
        pass
    try:  # keep the console readable when launched in its own window
        if _sys_boot.stdin and _sys_boot.stdin.isatty():
            input("Press Enter to close…")
    except Exception:
        pass
    _sys_boot.exit(1)


_THIS_DIR_BOOT = _Path_boot(__file__).resolve().parent
if str(_THIS_DIR_BOOT) not in _sys_boot.path:
    _sys_boot.path.insert(0, str(_THIS_DIR_BOOT))

try:
    from activity_stream import ActivityStream
    from kali_tools import TOOLS, list_tools, tool_help, run_tool, parse_args_with_preset
    import security_tools_installer  # canonical security tool installer (winget/choco)
    from file_browser import FileBrowser, get_browser
    from model_router import ModelRouter, TaskType, list_models, get_router, MODEL_CONFIGS
    from memory_handoff import save_context_chunk, load_recent_handoffs, get_handoff_summary
except ImportError as _e_boot:
    _fatal_import(_e_boot)
```

### THEN also guard persistence_logger

A little further down you have (unguarded):

```python
from persistence_logger import (
    log_skill_usage, log_task, log_tool_usage, log_spawned_agent,
    log_model_routing, log_wsl_kali_usage, log_dynamic_context_action
)
```

Wrap it so it uses the same helper:

```python
try:
    from persistence_logger import (
        log_skill_usage, log_task, log_tool_usage, log_spawned_agent,
        log_model_routing, log_wsl_kali_usage, log_dynamic_context_action
    )
except ImportError as _e_boot:
    _fatal_import(_e_boot)
```

Everything else in the file is unchanged: on success the imported names are
identical, so the rest of `agent_v2.py` behaves exactly as before.

---

## PATCH 2 — Cosmetic bug in the /voice handler

**FIND** (inside the `elif cmd == "voice":` block):

```python
                    print("\n🎤 Voice Module Status:")
                    print("= * 40")
```

**REPLACE WITH:**

```python
                    print("\n🎤 Voice Module Status:")
                    print("=" * 40)
```

`"= * 40"` printed the literal text; `"=" * 40` prints the divider you intended.

---

## How these were verified

- Both patches compile (`python -m py_compile`).
- PATCH 1 tested in isolation TWO ways:
  1. With a sibling module missing → prints the framed FATAL diagnostic,
     writes it to `logs/agent_startup_error.log`, and exits with code 1
     (instead of a raw traceback in a vanishing console).
  2. With all siblings present and exposing the needed names → passes through
     transparently, no exit, all names imported.
- I could NOT run the full `agent_v2.py` here (it needs Ollama, torch, ChromaDB,
  and the rest of the src/ tree), so PATCH 1/2 are verified at the
  import-guard and syntax level, not a full live boot. That live boot is yours
  to run on the sandbox PC.
