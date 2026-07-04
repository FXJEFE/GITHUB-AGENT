"""N8N workflow automation MCP Server."""
import os
import requests
from .base import BaseMCPServer


class N8NServer(BaseMCPServer):
    def __init__(self, base_url: str = "http://localhost:5678", api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("N8N_API_KEY", "")

    def _headers(self):
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            h["X-N8N-API-KEY"] = self.api_key
        return h

    def _req(self, method, path, **kwargs):
        try:
            resp = requests.request(method, f"{self.base_url}/api/v1{path}",
                                    headers=self._headers(), timeout=15, **kwargs)
            if resp.status_code >= 400:
                return {"error": f"n8n {resp.status_code}: {resp.text[:200]}"}
            return resp.json() if resp.text else {"success": True}
        except requests.ConnectionError:
            return {"error": "n8n not running (connection refused)"}

    def health_check(self) -> dict:
        return self._req("GET", "/health")

    def list_workflows(self, active: bool = None) -> dict:
        params = {}
        if active is not None:
            params["active"] = str(active).lower()
        return self._req("GET", "/workflows", params=params)

    def get_workflow(self, workflow_id: str) -> dict:
        return self._req("GET", f"/workflows/{workflow_id}")

    def activate_workflow(self, workflow_id: str) -> dict:
        return self._req("PATCH", f"/workflows/{workflow_id}/activate")

    def deactivate_workflow(self, workflow_id: str) -> dict:
        return self._req("PATCH", f"/workflows/{workflow_id}/deactivate")

    def execute_workflow(self, workflow_id: str, data: dict = None) -> dict:
        return self._req("POST", f"/workflows/{workflow_id}/execute", json=data or {})

    def list_executions(self, workflow_id: str = None, status: str = None) -> dict:
        params = {}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status
        return self._req("GET", "/executions", params=params)

    def get_execution(self, execution_id: str) -> dict:
        return self._req("GET", f"/executions/{execution_id}")

    def trigger_webhook(self, webhook_path: str, method: str = "POST", data: dict = None) -> dict:
        try:
            url = f"{self.base_url}/webhook/{webhook_path.lstrip('/')}"
            resp = requests.request(method, url, json=data or {}, timeout=15)
            return {"status": resp.status_code, "response": resp.text[:1000]}
        except Exception as e:
            return {"error": str(e)}
