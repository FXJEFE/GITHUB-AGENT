#!/usr/bin/env python3
"""
safe_code_executor.py — LARRY G-FORCE local execution layer.

Two public things live here:

  SafeCodeExecutor   the low-level engine that actually runs commands / code.
                     Timeouts, output caps, a kill-switch registry, a minimal
                     "catastrophic command" guard (overridable), and an optional
                     Docker Desktop sandbox mode.

  MCPToolkit         the high-level dispatcher the agent talks to. It owns the
                     executor + a FileBrowser and turns slash commands
                     (`/run`, `/edit`, `/read`, `/ls`, `/grep`, `/skill`, `/stop`)
                     into results. It also exposes get_tools() / call_tool() so
                     the same capabilities are available to Ollama function-calling,
                     and get_status() for the dashboard + smoke tests.

Design rules (match the rest of the codebase):
  * Import-light. `python -c "from safe_code_executor import get_executor"`
    must succeed on bare Python with no Ollama / config present.
  * Degrade, don't crash. Optional deps (kali_tools, file_browser, larry_paths,
    persistence_logger, docker) are imported defensively.
  * Every public call returns a predictable shape: dict for the engine,
    str for the slash dispatcher, list[dict] for tool schemas.

Slash commands handled by MCPToolkit.dispatch():
  /run  <command>                     run a shell command (local, sandboxed cwd)
  /run! <command>                     run even if it trips the safety guard
  /run --docker <command>             run inside a throwaway Docker container
  /py   <code>                        run a python snippet in a subprocess
  /edit <path> L<start>-<end> :: ...  replace lines start..end with text after ::
  /edit <path> ++ <text>              append text to a file
  /write <path> :: <content>          overwrite a file (keeps a .backup)
  /read <path> [start] [end]          read a file (line-numbered)
  /ls   [path]                        list a directory
  /grep <pattern> <path>              search within a file
  /skill <name> [args...]            run a registered skill
  /skills                             list registered skills
  /stop                               kill every running child process
  /help                               show this help

This module is the canonical home of MCPToolkit. mcp_client.get_mcp_toolkit()
imports it from here and wires in MCP servers + FXJEFE tools.
"""

from __future__ import annotations

__version__ = "2.0.0"

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── defensive optional imports ────────────────────────────────────────────────
try:
    import larry_paths  # zero-dep, travels with the repo
    _BASE_DIR = larry_paths.BASE_DIR
    _SANDBOX_DIR = getattr(larry_paths, "SANDBOX_DIR", _BASE_DIR / "sandbox")
except Exception:  # running outside the repo
    _BASE_DIR = Path(__file__).parent.resolve()
    _SANDBOX_DIR = _BASE_DIR / "sandbox"

try:
    from file_browser import get_browser  # /edit, /read, /ls backend
    _HAVE_BROWSER = True
except Exception:
    get_browser = None  # type: ignore
    _HAVE_BROWSER = False

try:
    # reuse the security-tool kill-switch so /stop also stops Kali scans
    from kali_tools import kill_all_tools as _kill_kali_tools
except Exception:
    def _kill_kali_tools() -> int:
        return 0

try:
    from persistence_logger import log_tool_usage as _log_tool
except Exception:
    def _log_tool(*a, **k):  # no-op if logging stack absent
        return None


# ── kill-switch registry (mirrors kali_tools._ACTIVE_PROCS) ───────────────────
_ACTIVE_PROCS: Dict[int, "subprocess.Popen"] = {}
_ACTIVE_LOCK = threading.Lock()


def _register(proc: "subprocess.Popen") -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS[id(proc)] = proc


def _unregister(proc: "subprocess.Popen") -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_PROCS.pop(id(proc), None)


def kill_all() -> int:
    """Terminate every child process this executor started, plus Kali tools."""
    with _ACTIVE_LOCK:
        procs = list(_ACTIVE_PROCS.values())
    killed = 0
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
                killed += 1
        except Exception:
            pass
    killed += _kill_kali_tools()
    return killed


# ── catastrophic-command guard ────────────────────────────────────────────────
# Intentionally tiny. This is a sandboxed personal box and the operator owns the
# risk — so this only blocks the handful of commands that can brick the host or
# wipe a disk. Anything else runs. Use /run! (or allow_dangerous=True) to bypass.
_DANGER_SUBSTRINGS: Tuple[str, ...] = (
    "rm -rf /", "rm -rf /*", "rm -fr /",
    ":(){:|:&};:",                    # fork bomb
    "mkfs", "dd if=", "> /dev/sda", "of=/dev/sd",
    "format c:", "format /q", "del /f /s /q c:\\",
    "shutdown", "reboot", "halt -f",
)


def _looks_catastrophic(command: str) -> Optional[str]:
    norm = " ".join(command.lower().split())
    for sig in _DANGER_SUBSTRINGS:
        if sig in norm:
            return sig
    return None


@dataclass
class ExecResult:
    """Uniform result of any execution. ``ok`` is the single source of truth."""
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration: float = 0.0
    mode: str = "local"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "stdout": self.stdout, "stderr": self.stderr,
            "exit_code": self.exit_code, "duration": round(self.duration, 3),
            "mode": self.mode, "note": self.note,
        }

    def render(self, max_chars: int = 8000) -> str:
        body = (self.stdout or "")
        if self.stderr:
            body += ("\n" if body else "") + self.stderr
        body = body.strip() or f"(no output, exit code {self.exit_code})"
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n... [truncated at {max_chars} chars]"
        head = "✅" if self.ok else "❌"
        tag = f" [{self.mode}]" if self.mode != "local" else ""
        return f"{head}{tag} exit={self.exit_code} ({self.duration:.1f}s)\n{body}"


class SafeCodeExecutor:
    """
    Runs shell commands and python snippets with timeouts, output caps,
    a kill-switch, a minimal danger guard, and an optional Docker sandbox.

    Nothing here imports Ollama or config — it is a pure execution primitive
    so it stays importable for smoke tests and reusable everywhere.
    """

    def __init__(
        self,
        workdir: Optional[str | Path] = None,
        default_timeout: int = 120,
        max_output: int = 8000,
        docker_image: str = "python:3.11-slim",
    ):
        self.workdir = Path(workdir).resolve() if workdir else _SANDBOX_DIR
        try:
            self.workdir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.workdir = Path(tempfile.gettempdir())
        self.default_timeout = default_timeout
        self.max_output = max_output
        self.docker_image = docker_image

    # ---- shell --------------------------------------------------------------
    def run_shell(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str | Path] = None,
        allow_dangerous: bool = False,
        env: Optional[Dict[str, str]] = None,
    ) -> ExecResult:
        command = command.strip()
        if not command:
            return ExecResult(ok=False, stderr="empty command")

        if not allow_dangerous:
            hit = _looks_catastrophic(command)
            if hit:
                return ExecResult(
                    ok=False,
                    stderr=(f"blocked: command matched catastrophic guard '{hit}'. "
                            f"Re-run with /run! or allow_dangerous=True if intended."),
                    note="guard",
                )

        timeout = timeout or self.default_timeout
        run_cwd = Path(cwd).resolve() if cwd else self.workdir
        run_env = {**os.environ, **(env or {})}
        start = time.time()
        proc = None
        try:
            proc = subprocess.Popen(
                command, shell=True, cwd=str(run_cwd),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=run_env,
            )
            _register(proc)
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return ExecResult(ok=False, stderr=f"timed out after {timeout}s",
                                  duration=time.time() - start, note="timeout")
            rc = proc.returncode
            if rc is not None and rc < 0:
                return ExecResult(ok=False, stderr=f"killed (signal {-rc})",
                                  exit_code=rc, duration=time.time() - start,
                                  note="killed")
            res = ExecResult(ok=(rc == 0), stdout=self._cap(out), stderr=self._cap(err),
                             exit_code=rc, duration=time.time() - start)
        except Exception as e:
            res = ExecResult(ok=False, stderr=f"executor error: {e}",
                             duration=time.time() - start, note="error")
        finally:
            if proc is not None:
                _unregister(proc)
        _log_tool("run_shell", {"command": command[:300]}, res.note or ("ok" if res.ok else "fail"),
                  source="executor")
        return res

    # ---- python -------------------------------------------------------------
    def run_python(self, code: str, timeout: Optional[int] = None,
                   allow_dangerous: bool = False) -> ExecResult:
        """Run a python snippet in a *fresh subprocess* (never exec in-process)."""
        code = code.strip()
        if not code:
            return ExecResult(ok=False, stderr="empty code")
        tmp = Path(tempfile.mkstemp(suffix=".py", dir=str(self.workdir))[1])
        try:
            tmp.write_text(code, encoding="utf-8")
            return self.run_shell(f'"{sys.executable}" "{tmp}"', timeout=timeout,
                                  allow_dangerous=True)  # guard already not relevant
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass

    # ---- docker sandbox -----------------------------------------------------
    def docker_available(self) -> bool:
        return shutil.which("docker") is not None

    def run_in_docker(self, command: str, timeout: Optional[int] = None,
                      image: Optional[str] = None) -> ExecResult:
        """
        Run a command inside a throwaway container. The toughest sandbox available
        on a Windows + Docker Desktop box: no host FS, no network, dropped caps.
        """
        if not self.docker_available():
            return ExecResult(ok=False, mode="docker",
                              stderr="docker not found on PATH (is Docker Desktop running?)",
                              note="no-docker")
        img = image or self.docker_image
        wrapped = (
            f'docker run --rm --network none '
            f'--memory 1g --cpus 1 --pids-limit 256 '
            f'--security-opt no-new-privileges '
            f'{shlex.quote(img)} sh -c {shlex.quote(command)}'
        )
        res = self.run_shell(wrapped, timeout=timeout, allow_dangerous=True)
        res.mode = "docker"
        return res

    def _cap(self, s: Optional[str]) -> str:
        s = s or ""
        if len(s) > self.max_output:
            return s[: self.max_output] + f"\n... [truncated at {self.max_output} chars]"
        return s

    def status(self) -> Dict[str, Any]:
        with _ACTIVE_LOCK:
            running = sum(1 for p in _ACTIVE_PROCS.values() if p.poll() is None)
        return {
            "workdir": str(self.workdir),
            "default_timeout": self.default_timeout,
            "running_processes": running,
            "docker_available": self.docker_available(),
            "docker_image": self.docker_image,
        }


# ── skill registry ────────────────────────────────────────────────────────────
@dataclass
class Skill:
    name: str
    fn: Callable[..., Any]
    description: str = ""
    usage: str = ""


class SkillRegistry:
    """Lightweight name -> callable registry, mirroring the agent's skills dict."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, name: str, fn: Callable[..., Any],
                 description: str = "", usage: str = "") -> None:
        self._skills[name] = Skill(name, fn, description, usage)

    def skill(self, name: str, description: str = "", usage: str = ""):
        """Decorator form: @registry.skill('greet', 'say hi')"""
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(name, fn, description, usage)
            return fn
        return deco

    def run(self, name: str, *args, **kwargs) -> Any:
        sk = self._skills.get(name)
        if sk is None:
            return f"❌ unknown skill '{name}'. Known: {', '.join(self._skills) or '(none)'}"
        try:
            return sk.fn(*args, **kwargs)
        except Exception as e:
            return f"❌ skill '{name}' failed: {e}"

    def list(self) -> List[Dict[str, str]]:
        return [{"name": s.name, "description": s.description, "usage": s.usage}
                for s in self._skills.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# ── MCPToolkit — the slash-command + tool-call dispatcher ─────────────────────
class MCPToolkit:
    """
    The agent-facing surface. Owns a SafeCodeExecutor + a FileBrowser and turns
    `/run` / `/edit` (and friends) into results. The same actions are exposed as
    tool schemas via get_tools()/call_tool() for Ollama function-calling.

    External wiring (MCP servers, FXJEFE local tools) is attached by
    mcp_client.get_mcp_toolkit() — this class works standalone without them.
    """

    def __init__(
        self,
        executor: Optional[SafeCodeExecutor] = None,
        base_dirs: Optional[List[str]] = None,
        mcp_client: Any = None,
        fxjefe: Any = None,
    ):
        self.executor = executor or get_executor()
        self.skills = SkillRegistry()
        # FileBrowser scoped to the project root (+ sandbox) by default.
        if _HAVE_BROWSER:
            dirs = base_dirs or [str(_BASE_DIR), str(_SANDBOX_DIR)]
            self.browser = get_browser(dirs)
        else:
            self.browser = None
        # Optional external surfaces (set by mcp_client). May be None.
        self.mcp_client = mcp_client
        self.fxjefe = fxjefe
        self._register_builtin_skills()

    # ---- builtin skills (examples; extend freely) -----------------------------
    def _register_builtin_skills(self) -> None:
        self.skills.register(
            "pwd", lambda *_: (self.browser.pwd() if self.browser else str(self.executor.workdir)),
            "print working directory", "/skill pwd")
        self.skills.register(
            "whoami", lambda *_: _safe_oneliner("whoami"),
            "current OS user", "/skill whoami")
        self.skills.register(
            "ports", lambda *_: self.executor.run_shell(
                "netstat -ano" if os.name == "nt" else "ss -tlnp").render(),
            "list listening ports", "/skill ports")

    # ---- the main entry point -------------------------------------------------
    def dispatch(self, line: str) -> str:
        """Parse one slash command line and return a human-readable result."""
        line = (line or "").strip()
        if not line:
            return self.help()
        if not line.startswith("/"):
            return ("Not a command. Prefix with '/'. Try /help. "
                    "(Plain prose should go to the LLM, not the toolkit.)")

        cmd, _, rest = line.partition(" ")
        cmd = cmd.lower()
        rest = rest.strip()

        if cmd in ("/help", "/?"):
            return self.help()
        if cmd == "/stop":
            n = kill_all()
            return f"🛑 stopped {n} running process(es)."
        if cmd in ("/run", "/run!"):
            return self._cmd_run(rest, force=(cmd == "/run!"))
        if cmd == "/py":
            return self.executor.run_python(rest).render(self.executor.max_output)
        if cmd == "/edit":
            return self._cmd_edit(rest)
        if cmd == "/write":
            return self._cmd_write(rest)
        if cmd == "/read":
            return self._cmd_read(rest)
        if cmd == "/ls":
            if not self.browser:
                return self.executor.run_shell(f"ls -la {rest}" if os.name != 'nt' else f"dir {rest}").render()
            return self.browser.ls(rest or ".")
        if cmd == "/grep":
            return self._cmd_grep(rest)
        if cmd == "/skill":
            name, _, args = rest.partition(" ")
            return str(self.skills.run(name, args.strip()))
        if cmd == "/skills":
            return "\n".join(f"  {s['name']:<12} {s['description']}" for s in self.skills.list()) or "(none)"
        if cmd == "/mcp":
            return self._cmd_mcp(rest)
        if cmd == "/fxjefe":
            if self.fxjefe and getattr(self.fxjefe, "available", False):
                return f"FXJEFE tools: {self.fxjefe.get_tools()}"
            return "FXJEFE local tools not available (server not connected)."
        return f"❌ unknown command '{cmd}'. Try /help."

    # ---- /run -----------------------------------------------------------------
    def _cmd_run(self, rest: str, force: bool = False) -> str:
        docker = False
        if rest.startswith("--docker"):
            docker = True
            rest = rest[len("--docker"):].strip()
        if not rest:
            return "usage: /run <command>   |   /run --docker <command>   |   /run! <command>"
        if docker:
            return self.executor.run_in_docker(rest).render(self.executor.max_output)
        return self.executor.run_shell(rest, allow_dangerous=force).render(self.executor.max_output)

    # ---- /edit ----------------------------------------------------------------
    def _cmd_edit(self, rest: str) -> str:
        """
        /edit <path> L<start>-<end> :: <new text>     replace a line range
        /edit <path> ++ <text>                         append
        """
        if not self.browser:
            return "❌ file_browser not available; /edit disabled."
        try:
            path, _, tail = rest.partition(" ")
            tail = tail.strip()
            if tail.startswith("++"):
                addition = tail[2:].strip()
                content, ok = self.browser.read_full(path)
                if not ok:
                    return f"❌ {content}"
                joined = content + ("" if content.endswith("\n") else "\n") + addition + "\n"
                return self.browser.write(path, joined)
            # line-range form:  L<start>-<end> :: text
            spec, _, new = tail.partition("::")
            spec = spec.strip().lstrip("Ll")
            new = new.strip()
            if "-" not in spec:
                return ("usage: /edit <path> L<start>-<end> :: <text>   "
                        "or   /edit <path> ++ <text>")
            s, e = spec.split("-", 1)
            return self.browser.edit_lines(path, int(s), int(e), new)
        except Exception as ex:
            return f"❌ /edit parse error: {ex}"

    def _cmd_write(self, rest: str) -> str:
        if not self.browser:
            return "❌ file_browser not available; /write disabled."
        path, _, content = rest.partition("::")
        path = path.strip()
        if not path:
            return "usage: /write <path> :: <content>"
        if content.startswith(" "):       # drop the single separator space
            content = content[1:]
        return self.browser.write(path, content.lstrip("\n"))

    def _cmd_read(self, rest: str) -> str:
        if not self.browser:
            return self.executor.run_shell(f"cat {rest}").render()
        parts = rest.split()
        if not parts:
            return "usage: /read <path> [start] [end]"
        path = parts[0]
        start = int(parts[1]) if len(parts) > 1 else 1
        end = int(parts[2]) if len(parts) > 2 else None
        return self.browser.read(path, start, end)

    def _cmd_grep(self, rest: str) -> str:
        if not self.browser:
            return "❌ file_browser not available; /grep disabled."
        parts = rest.split(None, 1)
        if len(parts) < 2:
            return "usage: /grep <pattern> <path>"
        return self.browser.grep(parts[0], parts[1])

    def _cmd_mcp(self, rest: str) -> str:
        if not self.mcp_client:
            return "No MCP client attached. Use mcp_client.get_mcp_toolkit() to wire servers."
        sub, _, args = rest.partition(" ")
        if sub in ("", "list", "status"):
            return str(self.mcp_client.status())
        if sub == "tools":
            return str(self.mcp_client.list_tools())
        return f"unknown /mcp subcommand '{sub}'. try: list | tools"

    # ---- tool schemas for Ollama function-calling -----------------------------
    def get_tools(self) -> List[Dict[str, Any]]:
        """JSON-schema tool definitions (Ollama / OpenAI 'tools' format)."""
        tools = [
            _tool("run_shell", "Run a shell command on the local machine and return its output.",
                  {"command": _p("string", "the shell command to execute"),
                   "timeout": _p("integer", "seconds before kill (optional)")},
                  required=["command"]),
            _tool("run_python", "Execute a short Python 3 snippet in an isolated subprocess.",
                  {"code": _p("string", "python source to run")}, required=["code"]),
            _tool("edit_file", "Replace a line range in a text file.",
                  {"path": _p("string", "file path"),
                   "start_line": _p("integer", "first line to replace (1-based)"),
                   "end_line": _p("integer", "last line to replace"),
                   "new_text": _p("string", "replacement text")},
                  required=["path", "start_line", "end_line", "new_text"]),
            _tool("write_file", "Overwrite a file with new content (a .backup is kept).",
                  {"path": _p("string", "file path"),
                   "content": _p("string", "full new content")},
                  required=["path", "content"]),
            _tool("read_file", "Read a text file, optionally a line range.",
                  {"path": _p("string", "file path"),
                   "start_line": _p("integer", "first line (optional)"),
                   "end_line": _p("integer", "last line (optional)")},
                  required=["path"]),
        ]
        if self.executor.docker_available():
            tools.append(_tool(
                "run_in_docker", "Run a command inside a throwaway, network-less Docker container.",
                {"command": _p("string", "command to run inside the container"),
                 "image": _p("string", "docker image (optional)")},
                required=["command"]))
        # surface registered skills as a single dispatch tool
        if self.skills.list():
            tools.append(_tool(
                "run_skill", "Run one of Larry's registered named skills.",
                {"name": _p("string", "skill name; one of: " +
                            ", ".join(s["name"] for s in self.skills.list())),
                 "args": _p("string", "argument string (optional)")},
                required=["name"]))
        return tools

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name. Returns {'ok':bool,'result':str}."""
        try:
            if name == "run_shell":
                r = self.executor.run_shell(args["command"], timeout=args.get("timeout"))
                return {"ok": r.ok, "result": r.render(self.executor.max_output)}
            if name == "run_python":
                r = self.executor.run_python(args["code"])
                return {"ok": r.ok, "result": r.render(self.executor.max_output)}
            if name == "run_in_docker":
                r = self.executor.run_in_docker(args["command"], image=args.get("image"))
                return {"ok": r.ok, "result": r.render(self.executor.max_output)}
            if name == "edit_file":
                if not self.browser:
                    return {"ok": False, "result": "file_browser unavailable"}
                out = self.browser.edit_lines(args["path"], int(args["start_line"]),
                                              int(args["end_line"]), args["new_text"])
                return {"ok": out.startswith("✅"), "result": out}
            if name == "write_file":
                if not self.browser:
                    return {"ok": False, "result": "file_browser unavailable"}
                out = self.browser.write(args["path"], args["content"])
                return {"ok": out.startswith("✅"), "result": out}
            if name == "read_file":
                if not self.browser:
                    out = self.executor.run_shell(f"cat {args['path']}").render()
                    return {"ok": True, "result": out}
                out = self.browser.read(args["path"], int(args.get("start_line", 1)),
                                        args.get("end_line"))
                return {"ok": not out.startswith("❌"), "result": out}
            if name == "run_skill":
                out = self.skills.run(args["name"], args.get("args", ""))
                return {"ok": True, "result": str(out)}
            return {"ok": False, "result": f"unknown tool '{name}'"}
        except KeyError as e:
            return {"ok": False, "result": f"missing argument {e}"}
        except Exception as e:
            return {"ok": False, "result": f"tool '{name}' error: {e}"}

    # ---- status / help --------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """Aggregate status. Includes 'fxjefe_tools' for manage_larry.py mcp-test."""
        fx_tools: List[str] = []
        if self.fxjefe and getattr(self.fxjefe, "available", False):
            try:
                fx_tools = list(self.fxjefe.get_tools())
            except Exception:
                fx_tools = []
        status = {
            "toolkit_version": __version__,
            "executor": self.executor.status(),
            "file_browser": _HAVE_BROWSER,
            "local_tools": [t["function"]["name"] for t in self.get_tools()],
            "skills": [s["name"] for s in self.skills.list()],
            "mcp_servers": (self.mcp_client.list_servers()
                            if self.mcp_client and hasattr(self.mcp_client, "list_servers")
                            else []),
            "fxjefe_available": bool(self.fxjefe and getattr(self.fxjefe, "available", False)),
            "fxjefe_tools": fx_tools,
        }
        return status

    def help(self) -> str:
        return (
            "LARRY G-FORCE toolkit commands:\n"
            "  /run  <cmd>                 run a shell command\n"
            "  /run! <cmd>                 run even if the safety guard trips\n"
            "  /run --docker <cmd>         run inside a throwaway container\n"
            "  /py   <code>                run a python snippet\n"
            "  /edit <path> L<s>-<e> :: t  replace lines s..e with t\n"
            "  /edit <path> ++ <text>      append text\n"
            "  /write <path> :: <content>  overwrite (keeps .backup)\n"
            "  /read <path> [s] [e]        read file (line numbers)\n"
            "  /ls   [path]                list a directory\n"
            "  /grep <pattern> <path>      search in a file\n"
            "  /skill <name> [args]        run a registered skill\n"
            "  /skills                     list skills\n"
            "  /mcp  [list|tools]          inspect connected MCP servers\n"
            "  /stop                       kill every running child process\n"
            "  /help                       this help"
        )


# ── small helpers for tool schemas ────────────────────────────────────────────
def _p(typ: str, desc: str) -> Dict[str, str]:
    return {"type": typ, "description": desc}


def _tool(name: str, desc: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def _safe_oneliner(cmd: str) -> str:
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip()
    except Exception as e:
        return f"(failed: {e})"


# ── singletons (the factory names manage_larry.py / mcp_client expect) ─────────
_executor: Optional[SafeCodeExecutor] = None
_toolkit: Optional[MCPToolkit] = None


def get_executor(**kwargs) -> SafeCodeExecutor:
    """Singleton SafeCodeExecutor. Imported by manage_larry.py smoke-test."""
    global _executor
    if _executor is None:
        _executor = SafeCodeExecutor(**kwargs)
    return _executor


def get_toolkit(**kwargs) -> MCPToolkit:
    """Singleton MCPToolkit (local-only). mcp_client wires the networked version."""
    global _toolkit
    if _toolkit is None:
        _toolkit = MCPToolkit(**kwargs)
    return _toolkit


# ── self-test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"safe_code_executor v{__version__}  (base={_BASE_DIR})")
    ex = get_executor()
    print("\n[1] run_shell echo:")
    print(ex.run_shell("echo hello from larry").render())

    print("\n[2] danger guard (should block):")
    print(ex.run_shell("rm -rf /").render())

    print("\n[3] run_python:")
    print(ex.run_python("print(2**10)").render())

    tk = get_toolkit()
    print("\n[4] /help:")
    print(tk.dispatch("/help")[:200], "...")

    print("\n[5] /run via dispatch:")
    print(tk.dispatch("/run echo dispatched"))

    print("\n[6] tool schemas:")
    for t in tk.get_tools():
        print("   •", t["function"]["name"])

    print("\n[7] call_tool run_shell:")
    print(tk.call_tool("run_shell", {"command": "echo tool-call-ok"}))

    print("\n[8] get_status (fxjefe_tools present?):")
    st = tk.get_status()
    print("   fxjefe_tools:", st["fxjefe_tools"], "| local_tools:", st["local_tools"])

    print("\n[9] docker available:", ex.docker_available())
    print("\n✅ safe_code_executor self-test complete.")
