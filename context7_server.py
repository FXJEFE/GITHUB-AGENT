"""Context7 library documentation MCP Server."""
import os
import json
import requests
from pathlib import Path
from .base import BaseMCPServer


class Context7Server(BaseMCPServer):
    """Fetches library docs via context7.com public API."""

    API = "https://context7.com/api"

    def __init__(self, cache_dir: str = "./context7_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def _cached(self, key: str):
        f = self.cache_dir / f"{key}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def _cache(self, key: str, data):
        (self.cache_dir / f"{key}.json").write_text(json.dumps(data, indent=2))

    def resolve_library_id(self, library_name: str, language: str = "python") -> dict:
        try:
            resp = requests.get(f"{self.API}/search", params={"q": library_name}, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            pass
        return {"library_id": library_name, "name": library_name, "note": "Context7 API unavailable - using library name as ID"}

    def get_library_docs(self, library_id: str, topic: str = None, max_tokens: int = 5000) -> dict:
        cache_key = f"docs_{library_id}_{topic or 'all'}"
        cached = self._cached(cache_key)
        if cached:
            return cached
        try:
            params = {"library": library_id, "max_tokens": max_tokens}
            if topic:
                params["topic"] = topic
            resp = requests.get(f"{self.API}/docs", params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self._cache(cache_key, data)
                return data
        except Exception:
            pass
        return {"library_id": library_id, "docs": f"Documentation for {library_id}", "note": "Fetched from cache or unavailable"}

    def search_docs(self, query: str, library_id: str = None, language: str = "python") -> list:
        try:
            params = {"q": query, "lang": language}
            if library_id:
                params["library"] = library_id
            resp = requests.get(f"{self.API}/search", params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("results", [])
        except Exception:
            pass
        return []

    def list_popular_libraries(self, language: str = "python") -> list:
        popular = {
            "python": ["requests", "numpy", "pandas", "fastapi", "sqlalchemy", "pydantic", "httpx", "aiohttp"],
            "javascript": ["react", "vue", "express", "lodash", "axios", "next.js"],
        }
        return [{"name": lib, "language": language} for lib in popular.get(language, [])]

    def get_function_docs(self, library_id: str, function_name: str) -> dict:
        return self.get_library_docs(library_id, topic=function_name)

    def get_examples(self, library_id: str, topic: str = None) -> list:
        result = self.get_library_docs(library_id, topic=topic)
        return result.get("examples", [])
