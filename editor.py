"""
subagents/editor.py — reads, writes and edits files autonomously.

Exposes read_file / write_file / edit_file tools plus run_terminal for
listing/searching, so the model can inspect before it modifies.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagents.base import SubAgent, PLATFORM_NOTE  # noqa: E402
from tools.terminal import RUN_TERMINAL_TOOL, run_terminal  # noqa: E402

MAX_READ = 60_000


def read_file(path: str, start_line: int = 1, max_chars: int = MAX_READ) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        text = "".join(lines[max(0, start_line - 1):])[:max_chars]
        return {"success": True, "path": path, "total_lines": len(lines), "content": text}
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}


def write_file(path: str, content: str) -> dict:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "path": path, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}


def edit_file(path: str, old_text: str, new_text: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        count = content.count(old_text)
        if count == 0:
            return {"success": False, "error": "old_text not found in file", "path": path}
        if count > 1:
            return {"success": False, "path": path,
                    "error": f"old_text occurs {count} times; provide a unique snippet"}
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old_text, new_text, 1))
        return {"success": True, "path": path}
    except Exception as e:
        return {"success": False, "error": str(e), "path": path}


def _tool(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


EDITOR_TOOLS = [
    _tool("read_file", "Read a text file (optionally from a start line).",
          {"path": {"type": "string", "description": "File path"},
           "start_line": {"type": "integer", "description": "1-based line to start at"}},
          ["path"]),
    _tool("write_file", "Create or overwrite a text file with the given content.",
          {"path": {"type": "string", "description": "File path"},
           "content": {"type": "string", "description": "Full file content"}},
          ["path", "content"]),
    _tool("edit_file", "Replace one unique occurrence of old_text with new_text in a file.",
          {"path": {"type": "string", "description": "File path"},
           "old_text": {"type": "string", "description": "Exact text to replace (must be unique)"},
           "new_text": {"type": "string", "description": "Replacement text"}},
          ["path", "old_text", "new_text"]),
    RUN_TERMINAL_TOOL,
]


class EditorAgent(SubAgent):
    NAME = "editor"
    TOOLS = EDITOR_TOOLS
    TOOL_FUNCTIONS = {
        "read_file": read_file,
        "write_file": write_file,
        "edit_file": edit_file,
        "run_terminal": run_terminal,
    }
    SYSTEM_PROMPT = (
        "You are EDITOR, a subagent of LARRY G-FORCE specialized in creating and "
        "modifying files on the user's local machine. Rules:\n"
        "- ALWAYS read_file before edit_file so old_text matches exactly.\n"
        "- Prefer edit_file for small changes, write_file for new files or rewrites.\n"
        "- Use run_terminal to list directories or search when needed. "
        f"{PLATFORM_NOTE}\n"
        "- After editing code, verify it if cheap (e.g. python -m py_compile).\n"
        "- Finish with a short summary of files changed and what changed."
    )


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Create a file named editor_smoke.txt in the sandbox folder containing the line: editor works"
    print(EditorAgent().run(task))
