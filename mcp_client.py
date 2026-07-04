#!/usr/bin/env python3
"""
mcp_client.py — LARRY G-FORCE MCP connector (local-only + Docker Desktop).

Responsibilities:
  * Load the server registry from mcp/mcp.json (Claude-Desktop-style format).
  * Talk to local MCP servers over stdio using newline-delimited JSON-RPC 2.0
    (the standard local transport). A server whose `command` is `docker` runs
    inside Docker Desktop — no special-casing needed, the config expresses it.
  * Provide list/initialize/tools.list/tools.call, with graceful degradation
    when a server isn't installed or Docker isn't running.
  * Expose FXJEFELocalTools — a thin wrapper around the FXJEFE local MCP server.
  * Provide get_mcp_toolkit(), which assembles a fully-wired MCPToolkit
    (local executor + MCP servers + FXJEFE) — the object manage_larry.py's
    `mcp-test` and `activate-all` expect.

No dependency on the official `mcp` SDK, so
`python -c "from mcp_client import MCPClient"` works on bare Python. For SSE /
streamable-HTTP servers (`"url": ...` entries) this client reports them as
present-but-not-dialed and points you at the SDK; stdio + Docker are fully live.

mcp.json shape (each value is a standard stdio server spec):
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\path"]
    },
    "fxjefe-local": {
      "command": "python",
      "args": ["mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py"]
    },
    "some-dockerized-server": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "ghcr.io/example/mcp-server:latest"]
    }
  }
}
"""

from __future__ import annotations

__version__ = "2.0.0"

import importlib
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# MCP protocol version we advertise on initialize. Bump to match your installed
# servers if any reject this (e.g. "2025-03-26"). Servers should negotiate down.
MCP_PROTOCOL_VERSION = "2024-11-05"

# ── defensive imports ─────────────────────────────────────────────────────────
try:
    import larry_paths
    _BASE_DIR: Path = larry_paths.BASE_DIR
    _MCP_CONFIG: Path = getattr(larry_paths, "MCP_CONFIG_FILE", _BASE_DIR / "mcp" / "mcp.json")
except Exception:
    _BASE_DIR = Path(__file__).parent.resolve()
    _MCP_CONFIG = _BASE_DIR / "mcp" / "mcp.json"

try:
    from persistence_logger import log_tool_usage as _log_tool
except Exception:
    def _log_tool(*a, **k):
        return None


# ── one stdio MCP server connection ───────────────────────────────────────────
class StdioMCPServer:
    """
    A single MCP server spoken to over stdio with newline-delimited JSON-RPC 2.0.
    Lazy: nothing is spawned until .start() is called.
    """

    def __init__(self, name: str, command: str, args: List[str],
                 env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd or str(_BASE_DIR)
        self.proc: Optional[subprocess.Popen] = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: List[Dict[str, Any]] = []
        self.initialized = False
        self.last_error: Optional[str] = None

    # ---- transport ----------------------------------------------------------
    @property
    def is_docker(self) -> bool:
        return self.command.lower() == "docker"

    def _binary_available(self) -> bool:
        return shutil.which(self.command) is not None

    def start(self, timeout: float = 20.0) -> bool:
        """Spawn the server, run the initialize handshake, cache tools/list."""
        if self.initialized:
            return True
        if not self._binary_available():
            self.last_error = (f"'{self.command}' not on PATH"
                               + (" (Docker Desktop running?)" if self.is_docker else ""))
            return False
        try:
            run_env = {**os.environ, **self.env}
            self.proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, cwd=self.cwd, env=run_env,
            )
        except Exception as e:
            self.last_error = f"spawn failed: {e}"
            return False

        # 1. initialize
        init = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "larry-g-force", "version": __version__},
        }, timeout=timeout)
        if init is None or "error" in init:
            self.last_error = f"initialize failed: {init.get('error') if init else 'no response'}"
            self.stop()
            return False
        # 2. initialized notification (no id, no response expected)
        self._notify("notifications/initialized")
        # 3. tools/list
        tl = self._request("tools/list", {}, timeout=timeout)
        if tl and "result" in tl:
            self.tools = tl["result"].get("tools", [])
        self.initialized = True
        return True

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, payload: Dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        line = json.dumps(payload) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        try:
            self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})
        except Exception as e:
            self.last_error = f"notify error: {e}"

    def _request(self, method: str, params: Dict[str, Any],
                 timeout: float = 20.0) -> Optional[Dict[str, Any]]:
        """Send a request and read newline-delimited responses until our id returns."""
        if not (self.proc and self.proc.stdin and self.proc.stdout):
            return None
        with self._lock:
            rid = self._next_id()
            try:
                self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            except Exception as e:
                self.last_error = f"send error: {e}"
                return None
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    self.last_error = "server exited"
                    return None
                line = self.proc.stdout.readline()
                if not line:
                    time.sleep(0.01)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # ignore non-JSON log noise on stdout
                # skip server-initiated notifications / other ids
                if msg.get("id") == rid:
                    return msg
            self.last_error = f"timeout waiting for '{method}'"
            return None

    def call_tool(self, tool: str, arguments: Dict[str, Any],
                  timeout: float = 60.0) -> Dict[str, Any]:
        if not self.initialized and not self.start():
            return {"ok": False, "error": self.last_error or "not initialized"}
        resp = self._request("tools/call",
                             {"name": tool, "arguments": arguments or {}}, timeout=timeout)
        if resp is None:
            return {"ok": False, "error": self.last_error or "no response"}
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        result = resp.get("result", {})
        # MCP returns content as a list of typed parts; flatten text for convenience
        text = _flatten_mcp_content(result.get("content", []))
        _log_tool(f"mcp:{self.name}:{tool}", arguments, text[:300], source="mcp")
        return {"ok": not result.get("isError", False), "result": text, "raw": result}

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except Exception:
                pass
        self.initialized = False

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name, "command": self.command, "docker": self.is_docker,
            "binary_available": self._binary_available(),
            "initialized": self.initialized, "tools": [t.get("name") for t in self.tools],
            "last_error": self.last_error,
        }


def _flatten_mcp_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: List[str] = []
    for c in content or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(json.dumps(c))
        else:
            parts.append(str(c))
    return "\n".join(parts)


# ── one in-process (native Python) MCP server ─────────────────────────────────
class NativeMCPServer:
    """Adapter exposing an in-process BaseMCPServer (mcp_servers/*) through the
    SAME interface MCPClient uses for StdioMCPServer. This is what lets native
    servers declared in mcp.json (transport "native") become first-class,
    callable servers — and, crucially, lets FilesystemServer actually receive
    and honor its `allowed_paths` param instead of being silently dropped for
    having no `command`."""

    # Public attrs/methods on the impl that are plumbing, not callable tools.
    _NON_TOOL = {"call"}

    def __init__(self, name: str, impl: Any):
        self.name = name
        self.impl = impl
        self.command = "<native>"
        self.last_error: Optional[str] = None
        self.initialized = False
        self.tools: List[Dict[str, Any]] = []

    @property
    def is_docker(self) -> bool:
        return False

    def _binary_available(self) -> bool:
        return True  # in-process — nothing to spawn

    def start(self, timeout: float = 20.0) -> bool:
        if self.initialized:
            return True
        names = [
            n for n in dir(self.impl)
            if not n.startswith("_") and n not in self._NON_TOOL
            and callable(getattr(self.impl, n, None))
        ]
        self.tools = [{"name": n} for n in sorted(names)]
        self.initialized = True
        return True

    def stop(self) -> None:
        self.initialized = False

    def call_tool(self, tool: str, arguments: Dict[str, Any],
                  timeout: float = 60.0) -> Dict[str, Any]:
        if not self.initialized:
            self.start()
        if tool not in {t["name"] for t in self.tools}:
            return {"ok": False, "error": f"unknown tool '{tool}' on native server '{self.name}'"}
        resp = self.impl.call(tool, arguments or {})
        if getattr(resp, "success", False):
            _log_tool(f"mcp:{self.name}:{tool}", arguments,
                      str(resp.result)[:300], source="mcp-native")
            return {"ok": True, "result": resp.result, "raw": resp.result}
        self.last_error = getattr(resp, "error", "native call failed")
        return {"ok": False, "error": self.last_error}

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name, "command": self.command, "docker": False,
            "binary_available": True, "initialized": self.initialized,
            "tools": [t.get("name") for t in self.tools], "last_error": self.last_error,
        }


# ── the registry / client ─────────────────────────────────────────────────────
class MCPClient:
    """
    Loads mcp.json and manages MCP server connections (stdio + Docker).

    `self.servers` is a dict {name: StdioMCPServer-or-config}; len(self.servers)
    is the configured server count (smoke test relies on this attribute existing).
    Servers are NOT auto-started — call start(name) or start_all() explicitly so
    importing this module is cheap and side-effect-free.
    """

    def __init__(self, config_path: Optional[str | Path] = None, autostart: bool = False):
        self.config_path = Path(config_path) if config_path else _MCP_CONFIG
        self.servers: Dict[str, StdioMCPServer] = {}
        self.url_servers: Dict[str, Dict[str, Any]] = {}   # SSE/HTTP — recorded, not dialed
        self._load_config()
        if autostart:
            self.start_all()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return
        servers = data.get("mcpServers", data.get("servers", {}))
        if isinstance(servers, list):
            # canonical mcp/mcp.json shape: a list of specs carrying their own "name"
            servers = {spec.get("name", f"server-{i}"): spec
                       for i, spec in enumerate(servers) if isinstance(spec, dict)}
        for name, spec in (servers or {}).items():
            if not isinstance(spec, dict):
                continue
            if spec.get("disabled") or spec.get("enabled") is False:
                continue
            if "url" in spec:  # remote transport — not handled by the stdio client
                self.url_servers[name] = spec
                continue
            # Native (in-process Python) servers: transport "native", or a
            # module/class pair with no command. Instantiate directly so their
            # params (e.g. filesystem allowed_paths) are actually honored.
            if spec.get("transport") == "native" or (
                    spec.get("module") and spec.get("class") and not spec.get("command")):
                native = self._load_native(name, spec)
                if native is not None:
                    self.servers[name] = native
                continue
            command = spec.get("command")
            if not command:
                continue
            self.servers[name] = StdioMCPServer(
                name=name, command=command, args=spec.get("args", []),
                env=spec.get("env", {}), cwd=spec.get("cwd"),
            )

    def _load_native(self, name: str, spec: Dict[str, Any]) -> Optional[NativeMCPServer]:
        """Instantiate an in-process BaseMCPServer from a native mcp.json spec,
        passing through constructor-relevant params (e.g. allowed_paths). Extra
        config keys the constructor doesn't accept (e.g. allowed_extensions) are
        dropped so they never crash load. Returns None on error (logged)."""
        try:
            mod = importlib.import_module(spec["module"])
            cls = getattr(mod, spec["class"])
            params = dict(spec.get("params") or {})
            sig = inspect.signature(cls.__init__)
            if not any(p.kind is inspect.Parameter.VAR_KEYWORD
                       for p in sig.parameters.values()):
                accepted = set(sig.parameters) - {"self"}
                dropped = [k for k in params if k not in accepted]
                if dropped:
                    logger.debug("native '%s': ignoring unsupported params %s", name, dropped)
                params = {k: v for k, v in params.items() if k in accepted}
            return NativeMCPServer(name, cls(**params))
        except Exception as e:
            logger.warning("native MCP server '%s' failed to load: %s", name, e)
            return None

    # ---- lifecycle ----------------------------------------------------------
    def start(self, name: str) -> bool:
        srv = self.servers.get(name)
        return srv.start() if srv else False

    def start_all(self) -> Dict[str, bool]:
        return {name: srv.start() for name, srv in self.servers.items()}

    def stop_all(self) -> None:
        for srv in self.servers.values():
            srv.stop()

    # ---- queries ------------------------------------------------------------
    def list_servers(self) -> List[str]:
        return list(self.servers.keys()) + list(self.url_servers.keys())

    def list_tools(self, name: Optional[str] = None) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        targets = [name] if name else list(self.servers.keys())
        for n in targets:
            srv = self.servers.get(n)
            if not srv:
                continue
            if not srv.initialized:
                srv.start()
            out[n] = [t.get("name") for t in srv.tools]
        return out

    def call_tool(self, server: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        srv = self.servers.get(server)
        if not srv:
            return {"ok": False, "error": f"unknown server '{server}'"}
        return srv.call_tool(tool, arguments)

    def status(self) -> Dict[str, Any]:
        return {
            "config": str(self.config_path),
            "config_found": self.config_path.exists(),
            "stdio_servers": {n: s.status() for n, s in self.servers.items()},
            "url_servers": list(self.url_servers.keys()),
            "count": len(self.servers) + len(self.url_servers),
        }

    def __len__(self) -> int:
        return len(self.servers) + len(self.url_servers)


# ── FXJEFE local tools wrapper ────────────────────────────────────────────────
class FXJEFELocalTools:
    """
    Thin wrapper around the FXJEFE Local MCP server
    (mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py).

    `.available` is True when the server script exists AND (if already connected
    through an MCPClient) the connection initialized. `.get_tools()` returns the
    tool names. Designed so manage_larry.py's mcp-test can introspect it safely.
    """

    DEFAULT_REL = Path("mcp") / "fxjefe-local-mcp" / "fxjefe_local_mcp_server.py"

    def __init__(self, client: Optional[MCPClient] = None,
                 server_name: str = "fxjefe-local"):
        self.client = client
        self.server_name = server_name
        self.script_path = _BASE_DIR / self.DEFAULT_REL

    @property
    def _server(self) -> Optional[StdioMCPServer]:
        if self.client and self.server_name in self.client.servers:
            return self.client.servers[self.server_name]
        return None

    @property
    def available(self) -> bool:
        # available if a configured server matches, else if the script is on disk
        srv = self._server
        if srv is not None:
            return srv._binary_available()
        return self.script_path.exists()

    def get_tools(self) -> List[str]:
        srv = self._server
        if srv is None:
            return []
        if not srv.initialized:
            srv.start()
        return [t.get("name") for t in srv.tools]

    def call(self, tool: str, **arguments) -> Dict[str, Any]:
        srv = self._server
        if srv is None:
            return {"ok": False, "error": "fxjefe-local server not configured in mcp.json"}
        return srv.call_tool(tool, arguments)


# ── factory: fully-wired toolkit ──────────────────────────────────────────────
_client: Optional[MCPClient] = None
_mcp_toolkit: Any = None


def get_client(autostart: bool = False) -> MCPClient:
    global _client
    if _client is None:
        _client = MCPClient(autostart=autostart)
    return _client


def get_mcp_toolkit(autostart: bool = False) -> Any:
    """
    Assemble and return a fully-wired MCPToolkit:
      local executor + file tools  (from safe_code_executor)
      + MCP servers                (this module)
      + FXJEFE local tools.

    This is what manage_larry.py's `mcp-test` and `activate-all` call. The
    returned object exposes .get_status() (with 'fxjefe_tools') and .fxjefe.
    """
    global _mcp_toolkit
    if _mcp_toolkit is not None:
        return _mcp_toolkit

    client = get_client(autostart=autostart)
    fxjefe = FXJEFELocalTools(client=client)

    try:
        from safe_code_executor import MCPToolkit, get_executor
        _mcp_toolkit = MCPToolkit(executor=get_executor(),
                                  mcp_client=client, fxjefe=fxjefe)
    except Exception as e:
        # If the executor module is unavailable, fall back to a minimal shim that
        # still satisfies the introspection contract used by the smoke tests.
        _mcp_toolkit = _ToolkitShim(client=client, fxjefe=fxjefe, error=str(e))
    return _mcp_toolkit


class _ToolkitShim:
    """Fallback toolkit if safe_code_executor can't be imported. Read-only."""

    def __init__(self, client: MCPClient, fxjefe: FXJEFELocalTools, error: str = ""):
        self.mcp_client = client
        self.fxjefe = fxjefe
        self._error = error

    def get_status(self) -> Dict[str, Any]:
        return {
            "toolkit": "shim (safe_code_executor unavailable)",
            "error": self._error,
            "mcp_servers": self.mcp_client.list_servers(),
            "fxjefe_available": self.fxjefe.available,
            "fxjefe_tools": self.fxjefe.get_tools() if self.fxjefe.available else [],
        }

    def dispatch(self, line: str) -> str:
        return f"toolkit shim active ({self._error}); local /run /edit disabled."


# ── self-test (no servers required) ───────────────────────────────────────────
if __name__ == "__main__":
    print(f"mcp_client v{__version__}  (config={_MCP_CONFIG})")

    print("\n[1] MCPClient loads (no servers required):")
    c = MCPClient()
    print("   servers configured:", len(c.servers), "| names:", c.list_servers())
    print("   status.config_found:", c.status()["config_found"])

    print("\n[2] get_mcp_toolkit() wires local executor + mcp + fxjefe:")
    t = get_mcp_toolkit()
    st = t.get_status()
    print("   has .fxjefe:", hasattr(t, "fxjefe"))
    print("   fxjefe_available:", st.get("fxjefe_available"))
    print("   fxjefe_tools:", st.get("fxjefe_tools"))
    print("   local_tools:", st.get("local_tools", "(shim)"))

    print("\n[3] dispatch a local /run through the wired toolkit:")
    print("  ", t.dispatch("/run echo wired-through-mcp-toolkit").replace("\n", " | "))

    print("\n✅ mcp_client self-test complete.")
