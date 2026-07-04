"""
subagents/searcher.py — finds information: vector memory, local files, web.

Tools: recall_memory (ChromaDB), search_files (local grep-style search),
fetch_url (plain HTTP GET), run_terminal as a fallback.
"""

import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagents.base import SubAgent  # noqa: E402
from tools.terminal import RUN_TERMINAL_TOOL, run_terminal  # noqa: E402
from utils.memory_manager import MemoryManager  # noqa: E402

_memory = None


def recall_memory(query: str, n: int = 5) -> dict:
    global _memory
    try:
        if _memory is None:
            _memory = MemoryManager()
        return {"success": True, "results": _memory.recall(query, n=n)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def search_files(pattern: str, directory: str, extensions: str = "") -> dict:
    """Case-insensitive substring/regex search across text files."""
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"success": False, "error": f"Bad regex: {e}"}
    exts = {e.strip().lower().lstrip(".") for e in extensions.split(",") if e.strip()}
    skip_dirs = {".venv", "venv", "__pycache__", "node_modules", ".git", "chroma_db"}
    hits, scanned = [], 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if exts and fname.rsplit(".", 1)[-1].lower() not in exts:
                continue
            fpath = os.path.join(root, fname)
            try:
                if os.path.getsize(fpath) > 2_000_000:
                    continue
                scanned += 1
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if rx.search(line):
                            hits.append(f"{fpath}:{i}: {line.strip()[:200]}")
                            if len(hits) >= 50:
                                return {"success": True, "truncated": True,
                                        "files_scanned": scanned, "matches": hits}
            except OSError:
                continue
    return {"success": True, "files_scanned": scanned, "matches": hits}


def fetch_url(url: str, max_chars: int = 20000) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LarryAgent)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(500_000).decode("utf-8", errors="replace")
        # crude de-HTML so the model gets readable text
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"success": True, "url": url, "content": text[:max_chars]}
    except Exception as e:
        return {"success": False, "error": str(e), "url": url}


def _tool(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required}}}


SEARCHER_TOOLS = [
    _tool("recall_memory", "Semantic search over the agent's long-term vector memory (ChromaDB).",
          {"query": {"type": "string", "description": "What to look for"},
           "n": {"type": "integer", "description": "Number of results (default 5)"}},
          ["query"]),
    _tool("search_files", "Regex search inside text files under a directory.",
          {"pattern": {"type": "string", "description": "Regex (case-insensitive)"},
           "directory": {"type": "string", "description": "Root directory to search"},
           "extensions": {"type": "string", "description": "Comma-separated extensions, e.g. 'py,md'"}},
          ["pattern", "directory"]),
    _tool("fetch_url", "HTTP GET a URL and return readable page text.",
          {"url": {"type": "string", "description": "Full http(s) URL"}},
          ["url"]),
    RUN_TERMINAL_TOOL,
]


class SearcherAgent(SubAgent):
    NAME = "searcher"
    TOOLS = SEARCHER_TOOLS
    TOOL_FUNCTIONS = {
        "recall_memory": recall_memory,
        "search_files": search_files,
        "fetch_url": fetch_url,
        "run_terminal": run_terminal,
    }
    SYSTEM_PROMPT = (
        "You are SEARCHER, a subagent of LARRY G-FORCE specialized in finding "
        "information. Pick the right tool: recall_memory for things the agent "
        "may have stored, search_files for local code/docs, fetch_url for web "
        "pages, run_terminal only when nothing else fits.\n"
        "Answer with the facts found and where they came from. If nothing is "
        "found, say so plainly."
    )


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Search the src directory for files that mention 'chroma_db' and list them"
    print(SearcherAgent().run(task))
