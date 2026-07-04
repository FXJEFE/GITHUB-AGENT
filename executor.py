"""
subagents/executor.py — runs terminal commands autonomously.

The workhorse subagent: given a task, it executes shell commands via
tools/terminal.py until the task is done, then reports the result.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagents.base import SubAgent, PLATFORM_NOTE  # noqa: E402
from tools.terminal import AVAILABLE_TOOLS, TOOL_FUNCTIONS  # noqa: E402


class ExecutorAgent(SubAgent):
    NAME = "executor"
    TOOLS = AVAILABLE_TOOLS
    TOOL_FUNCTIONS = TOOL_FUNCTIONS
    SYSTEM_PROMPT = (
        "You are EXECUTOR, a subagent of LARRY G-FORCE running on the user's "
        "local machine. You complete tasks by executing terminal commands "
        "with the run_terminal tool. Rules:\n"
        f"- {PLATFORM_NOTE}\n"
        "- Always execute commands to verify facts; never guess output.\n"
        "- Chain steps: inspect, act, verify.\n"
        "- When the task is complete, reply with a short plain-text summary of "
        "what was done and the key output. Do not call tools after that."
    )


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Check what is listening on port 11434 and show me the processes"
    agent = ExecutorAgent()
    print(agent.run(task))
