#!/usr/bin/env python3
"""
MCP Supervisor — auto-activation + self-healing for Larry's MCP servers.

Wraps the side-effect-free `MCPClient` (mcp_client.py) and adds the bits it
deliberately leaves out:

  • auto-start ALL enabled servers from mcp.json at boot (with per-server retry)
  • periodic health checks (a background daemon thread)
  • self-healing: any server that died / never initialized is restarted, with
    exponential backoff and a failure ceiling so a permanently-broken server is
    quarantined instead of thrashing

Designed to be imported cheaply: nothing starts until you construct the
supervisor with autostart=True (or call .start()). Every external call is
wrapped so a failure here can NEVER crash the agent / telegram bot at startup.

Usage:
    from mcp_supervisor import get_mcp_supervisor
    sup = get_mcp_supervisor(autostart=True)   # boots + self-heals in background
    sup.status()                               # introspect
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from mcp_client import MCPClient
except Exception as e:  # pragma: no cover - import guarded so we never hard-fail
    MCPClient = None  # type: ignore
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


class MCPSupervisor:
    """Owns an MCPClient and keeps its servers alive."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        autostart: bool = True,
        heal_interval: float = 60.0,
        max_retries: int = 3,
        max_consecutive_failures: int = 5,
    ) -> None:
        self.heal_interval = max(10.0, float(heal_interval))
        self.max_retries = max(1, int(max_retries))
        self.max_consecutive_failures = max(1, int(max_consecutive_failures))

        self.client: Optional[MCPClient] = None
        # name -> consecutive failure count; a server hitting the ceiling is
        # quarantined (skipped by the healer) until manually re-enabled.
        self._failures: Dict[str, int] = {}
        self._quarantined: set[str] = set()
        self._lock = threading.RLock()
        self._heal_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_heal: float = 0.0

        if MCPClient is None:
            logger.warning("MCP supervisor disabled — mcp_client import failed: %s", _IMPORT_ERROR)
            return

        try:
            # autostart=False here: WE own the start sequence (with retry) below.
            self.client = MCPClient(config_path=config_path, autostart=False)
        except Exception as e:
            logger.warning("MCP supervisor: could not construct MCPClient: %s", e)
            self.client = None
            return

        if autostart:
            self.start()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> Dict[str, bool]:
        """Start every configured server (with retry) and launch the healer."""
        results = self._start_all_with_retry()
        self._start_healer()
        up = sum(1 for ok in results.values() if ok)
        logger.info("MCP supervisor: %d/%d servers up at boot.", up, len(results))
        return results

    def _start_one(self, name: str) -> bool:
        if self.client is None:
            return False
        srv = self.client.servers.get(name)
        if srv is None:
            return False
        for attempt in range(1, self.max_retries + 1):
            try:
                if getattr(srv, "initialized", False):
                    return True
                if srv.start():
                    self._failures[name] = 0
                    self._quarantined.discard(name)
                    return True
            except Exception as e:
                logger.debug("MCP '%s' start attempt %d failed: %s", name, attempt, e)
            time.sleep(min(2.0 * attempt, 6.0))  # linear-ish backoff between tries
        return False

    def _start_all_with_retry(self) -> Dict[str, bool]:
        out: Dict[str, bool] = {}
        if self.client is None:
            return out
        for name in list(self.client.servers.keys()):
            ok = self._start_one(name)
            out[name] = ok
            if not ok:
                self._failures[name] = self._failures.get(name, 0) + 1
        return out

    # ── self-healing ─────────────────────────────────────────────────────────
    def _is_healthy(self, name: str) -> bool:
        srv = self.client.servers.get(name) if self.client else None
        if srv is None:
            return False
        # Native servers are healthy once initialized; stdio servers also expose
        # a live subprocess we can probe via their own status() if present.
        if not getattr(srv, "initialized", False):
            return False
        proc = getattr(srv, "process", None)
        if proc is not None:
            try:
                return proc.poll() is None
            except Exception:
                return True
        return True

    def heal(self) -> Dict[str, str]:
        """One healing pass. Returns {name: action} for anything touched."""
        actions: Dict[str, str] = {}
        if self.client is None:
            return actions
        with self._lock:
            for name in list(self.client.servers.keys()):
                if name in self._quarantined:
                    continue
                if self._is_healthy(name):
                    self._failures[name] = 0
                    continue
                # unhealthy -> attempt restart
                try:
                    srv = self.client.servers.get(name)
                    if srv is not None:
                        try:
                            srv.stop()
                        except Exception:
                            pass
                    if self._start_one(name):
                        actions[name] = "restarted"
                        logger.info("MCP supervisor: healed server '%s'.", name)
                        continue
                except Exception as e:
                    logger.debug("MCP heal of '%s' raised: %s", name, e)
                self._failures[name] = self._failures.get(name, 0) + 1
                if self._failures[name] >= self.max_consecutive_failures:
                    self._quarantined.add(name)
                    actions[name] = "quarantined"
                    logger.warning(
                        "MCP supervisor: quarantined '%s' after %d failed heals.",
                        name, self._failures[name],
                    )
                else:
                    actions[name] = "restart_failed"
            self._last_heal = time.time()
        return actions

    def _start_healer(self) -> None:
        if self._heal_thread and self._heal_thread.is_alive():
            return
        if self.client is None:
            return
        self._stop.clear()
        self._heal_thread = threading.Thread(
            target=self._heal_loop, name="mcp-supervisor-healer", daemon=True
        )
        self._heal_thread.start()

    def _heal_loop(self) -> None:
        while not self._stop.wait(self.heal_interval):
            try:
                self.heal()
            except Exception as e:  # never let the healer die
                logger.debug("MCP heal loop error: %s", e)

    def unquarantine(self, name: str) -> bool:
        """Manually clear a quarantine and retry the server."""
        with self._lock:
            self._quarantined.discard(name)
            self._failures[name] = 0
        return self._start_one(name)

    def stop(self) -> None:
        self._stop.set()
        if self.client is not None:
            try:
                self.client.stop_all()
            except Exception:
                pass

    # ── introspection ────────────────────────────────────────────────────────
    def status(self) -> Dict[str, Any]:
        if self.client is None:
            return {"available": False, "reason": str(_IMPORT_ERROR)}
        servers = {}
        for name in self.client.servers.keys():
            servers[name] = {
                "healthy": self._is_healthy(name),
                "failures": self._failures.get(name, 0),
                "quarantined": name in self._quarantined,
            }
        return {
            "available": True,
            "config": str(getattr(self.client, "config_path", "")),
            "servers": servers,
            "url_servers": list(getattr(self.client, "url_servers", {}).keys()),
            "healthy_count": sum(1 for s in servers.values() if s["healthy"]),
            "total": len(servers),
            "last_heal": self._last_heal,
            "healer_alive": bool(self._heal_thread and self._heal_thread.is_alive()),
        }


# ── singleton ─────────────────────────────────────────────────────────────────
_supervisor: Optional[MCPSupervisor] = None
_singleton_lock = threading.Lock()


def get_mcp_supervisor(
    config_path: Optional[str] = None,
    autostart: bool = True,
    **kwargs: Any,
) -> MCPSupervisor:
    """Process-wide MCP supervisor. First call boots + self-heals; later calls
    return the same instance."""
    global _supervisor
    with _singleton_lock:
        if _supervisor is None:
            _supervisor = MCPSupervisor(config_path=config_path, autostart=autostart, **kwargs)
    return _supervisor


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sup = get_mcp_supervisor(autostart=True)
    import json as _json
    print(_json.dumps(sup.status(), indent=2, default=str))
