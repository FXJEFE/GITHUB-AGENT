"""Native Brave Search MCP Server."""
import os
import requests
from .base import BaseMCPServer


class BraveSearchServer(BaseMCPServer):
    BASE = "https://api.search.brave.com/res/v1"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")

    def _headers(self):
        return {"Accept": "application/json", "X-Subscription-Token": self.api_key}

    def web_search(self, query: str, count: int = 10) -> dict:
        if not self.api_key:
            return {"error": "BRAVE_API_KEY not set in .env"}
        resp = requests.get(
            f"{self.BASE}/web/search",
            headers=self._headers(),
            params={"q": query, "count": min(count, 20)},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"error": f"Brave API {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        results = []
        for r in data.get("web", {}).get("results", []):
            results.append({"title": r.get("title"), "url": r.get("url"), "description": r.get("description")})
        return {"query": query, "results": results, "count": len(results)}

    def news_search(self, query: str, count: int = 10) -> dict:
        if not self.api_key:
            return {"error": "BRAVE_API_KEY not set in .env"}
        resp = requests.get(
            f"{self.BASE}/news/search",
            headers=self._headers(),
            params={"q": query, "count": min(count, 20)},
            timeout=15,
        )
        if resp.status_code != 200:
            return {"error": f"Brave API {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        results = []
        for r in data.get("results", []):
            results.append({"title": r.get("title"), "url": r.get("url"), "age": r.get("age")})
        return {"query": query, "results": results, "count": len(results)}
