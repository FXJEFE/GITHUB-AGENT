"""Native Filesystem MCP Server."""
import os
import fnmatch
from pathlib import Path
from typing import List
from .base import BaseMCPServer


class FilesystemServer(BaseMCPServer):
    def __init__(self, allowed_paths: List[str] = None):
        self.allowed = [Path(p).resolve() for p in (allowed_paths or [str(Path.cwd())])]

    def _safe_path(self, path: str) -> Path:
        p = Path(path).resolve()
        if not any(str(p).startswith(str(a)) for a in self.allowed):
            # Allow absolute paths that exist within cwd as fallback
            cwd = Path.cwd().resolve()
            if not str(p).startswith(str(cwd)):
                raise PermissionError(f"Path not in allowed list: {p}")
        return p

    def read_file(self, path: str) -> dict:
        p = self._safe_path(path)
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "content": content, "size": p.stat().st_size}

    def write_file(self, path: str, content: str) -> dict:
        p = self._safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "bytes_written": len(content.encode())}

    def list_directory(self, path: str = ".") -> dict:
        p = self._safe_path(path)
        items = []
        for item in sorted(p.iterdir()):
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return {"path": str(p), "items": items, "count": len(items)}

    def search_files(self, pattern: str, path: str = ".") -> dict:
        p = self._safe_path(path)
        matches = []
        for root, dirs, files in os.walk(p):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if fnmatch.fnmatch(f, pattern):
                    matches.append(str(Path(root) / f))
        return {"pattern": pattern, "matches": matches, "count": len(matches)}

    def file_info(self, path: str) -> dict:
        p = self._safe_path(path)
        st = p.stat()
        return {
            "path": str(p), "exists": True, "is_file": p.is_file(),
            "is_dir": p.is_dir(), "size": st.st_size,
            "modified": st.st_mtime,
        }
