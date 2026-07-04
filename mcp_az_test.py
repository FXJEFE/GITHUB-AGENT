#!/usr/bin/env python3
"""
A-Z smoke test of Larry's agentic MCP host + tool loop, in a visible console.

It boots the REAL mcp_host (filesystem + fetch + shell), lists the tools, then
drives the LocalLarry-Agentic model through one autonomous task:
  • look up Oslo, Norway (web fetch)
  • look up the current XAU/USD gold price (web fetch)
  • write a Markdown report into the project dir (filesystem tool)

Artifacts (so the run can be verified after the window closes):
  • report : mcp_az_test_report.md   (in the repo root — the deliverable)
  • log    : <scratchpad>/az.log
  • done   : <scratchpad>/az.done    (sentinel: "OK" / "ERR: ...")
"""
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

REPORT = REPO / "mcp_az_test_report.md"
SCRATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir())
LOG = SCRATCH / "az.log"
DONE = SCRATCH / "az.done"

_logf = open(LOG, "w", encoding="utf-8")


def say(msg=""):
    line = str(msg)
    print(line, flush=True)
    _logf.write(line + "\n")
    _logf.flush()


def banner(t):
    say("\n" + "=" * 70)
    say(f"  {t}")
    say("=" * 70)


# A focused subset of the real servers.json: exactly the tools this task needs
# (skips the ~2-min cold RAG load + youtube for a snappy demo). Same real
# servers, same real agent loop.
def trimmed_config() -> str:
    full = json.loads((REPO / "mcp_host" / "servers.json").read_text(encoding="utf-8"))
    keep = {k: v for k, v in full["mcpServers"].items() if k in ("filesystem", "websearch")}
    cfg = SCRATCH / "servers.test.json"
    cfg.write_text(json.dumps({"mcpServers": keep}, indent=2), encoding="utf-8")
    return str(cfg)


TASK = f"""You are running an automated self-test. Use your MCP tools to do ALL of this, then reply DONE.

1. Call web_search with query "Oslo Norway population facts" and note 3 concise facts about Oslo, Norway (population, that it is the capital of Norway, one more).
2. Call web_search with query "current XAU USD gold spot price" and report the price number you find.
3. Call the filesystem write_file tool to write a Markdown file to this EXACT path:
   {REPORT}
   The file must contain: a "# Larry MCP A-Z Test" title, an "## Oslo, Norway" section with the 3 facts, an "## XAU/USD" section with the gold price and the source URL, and a final line "Generated: <UTC time>".

Use absolute paths. After the file is written, reply with DONE and a one-sentence summary."""


def main():
    status = "ERR: unknown"
    try:
        banner("LARRY MCP A-Z TEST  —  agent + tools, end to end")
        say(f"Repo     : {REPO}")
        say(f"Report   : {REPORT}")
        say(f"Started  : {datetime.now(timezone.utc).isoformat()}")

        banner("STEP 1/4  —  boot the MCP host (filesystem + websearch)")
        from mcp_host import MCPRunner
        cfg = trimmed_config()
        say(f"config: {cfg}")
        runner = MCPRunner(model="qwen3:8b", config_path=cfg, max_turns=10)
        say("waiting for servers to spawn (npx/uvx first run can download)…")
        if not runner.wait_ready(timeout=240):
            raise TimeoutError("MCP host did not become ready in 240s")
        say(runner.status_line())

        banner("STEP 2/4  —  available tools (A-Z)")
        for t in runner.tool_names():
            say(f"  • {t}")

        banner("STEP 3/4  —  run the agent on the task")
        say(TASK)
        say("\n--- agent working (model + tool round-trips) ---")
        t0 = time.time()
        result = runner.run_sync(TASK, timeout=480, ready_timeout=240)
        dt = time.time() - t0

        say(f"\n--- agent finished in {dt:.0f}s, {result.turns} turn(s) ---")
        say("\nTOOL CALLS MADE:")
        for i, c in enumerate(result.tool_calls_made, 1):
            say(f"  [{i}] {c['tool']}  args={c['arguments']}")
            say(f"       -> {c['result_preview'][:160].replace(chr(10),' ')}")
        say("\nAGENT FINAL ANSWER:")
        say(result.answer or "(empty)")

        banner("STEP 4/4  —  verify the written report")
        if REPORT.exists():
            say(f"✅ FILE EXISTS: {REPORT}  ({REPORT.stat().st_size} bytes)\n")
            say(REPORT.read_text(encoding="utf-8"))
            status = "OK"
        else:
            say(f"❌ report not found at {REPORT} — agent did not write it.")
            status = "ERR: no report file"

        try:
            runner.shutdown(timeout=10)
        except Exception:
            pass
    except Exception as e:
        import traceback
        say("\n!!! TEST ERROR !!!")
        say(traceback.format_exc())
        status = f"ERR: {type(e).__name__}: {e}"
    finally:
        banner(f"RESULT: {status}")
        DONE.write_text(status, encoding="utf-8")
        _logf.close()


if __name__ == "__main__":
    main()
