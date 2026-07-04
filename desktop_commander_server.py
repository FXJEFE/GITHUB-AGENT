"""Desktop Commander MCP Server (Linux/Ubuntu stub)."""
import subprocess
from .base import BaseMCPServer


class DesktopCommanderServer(BaseMCPServer):
    def __init__(self, allowed_apps: list = None):
        self.allowed_apps = allowed_apps or []

    def open_app(self, app: str) -> dict:
        if self.allowed_apps and app not in self.allowed_apps:
            return {"error": f"App not in allowed list: {app}"}
        try:
            subprocess.Popen([app], start_new_session=True)
            return {"launched": app}
        except FileNotFoundError:
            return {"error": f"App not found: {app}"}

    def get_windows(self) -> dict:
        try:
            result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
            return {"windows": result.stdout.strip().splitlines()}
        except FileNotFoundError:
            return {"error": "wmctrl not installed (apt install wmctrl)"}
