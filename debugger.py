"""
subagents/debugger.py — diagnoses and fixes failing code/services.

Highest max_turns of the subagents: it loops run -> read error ->
inspect -> patch -> re-run until the failure is resolved or turns run out.
Reuses the editor's file tools plus the terminal.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagents.base import SubAgent, PLATFORM_NOTE  # noqa: E402
from subagents.editor import EDITOR_TOOLS, read_file, write_file, edit_file  # noqa: E402
from tools.terminal import run_terminal  # noqa: E402


class DebuggerAgent(SubAgent):
    NAME = "debugger"
    TOOLS = EDITOR_TOOLS  # read_file / write_file / edit_file / run_terminal
    TOOL_FUNCTIONS = {
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "run_terminal": run_terminal,
    }
    SYSTEM_PROMPT = (
        "You are DEBUGGER, a subagent of LARRY G-FORCE that diagnoses and fixes "
        "failing code and services on the user's local machine. "
        f"{PLATFORM_NOTE} Method:\n"
        "1. Reproduce: run the failing command/script with run_terminal and "
        "capture the exact error.\n"
        "2. Inspect: read_file around the failure point (full traceback first).\n"
        "3. Fix: apply the smallest change that addresses the root cause with "
        "edit_file. Never paper over errors with try/except.\n"
        "4. Verify: re-run the original command and confirm the error is gone.\n"
        "Finish with: root cause, the fix applied, and proof it now works. "
        "If you cannot fix it within your turns, report the diagnosis honestly."
    )


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Run 'python --version' and report the environment"
    print(DebuggerAgent().run(task))
