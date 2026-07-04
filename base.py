"""
subagents/base.py — shared autonomous tool-calling loop for all subagents.

Uses Ollama's NATIVE tool calling (no regex detection, no LangChain).
Each subagent subclasses SubAgent and supplies: name, system prompt,
tool definitions, and a dispatch table of python callables.
"""

import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG, OLLAMA_HOST, subagent_config  # noqa: E402

# Subagent prompts embed this so commands match the actual runtime platform
# (Windows host vs Linux Docker container).
if os.name == "nt":
    PLATFORM_NOTE = (
        "The local system is Windows; the shell is cmd.exe (via subprocess "
        "shell=True). Use Windows commands (dir, type, tasklist, netstat) or "
        "call powershell -Command \"...\" when you need PowerShell."
    )
else:
    PLATFORM_NOTE = (
        "The local system is Linux; the shell is /bin/sh (via subprocess "
        "shell=True). Use standard Unix commands (ls, cat, ps, ss, grep)."
    )


def _ollama_chat(model: str, messages: list, tools: list = None,
                 options: dict = None, timeout: int = None,
                 format: str = None) -> dict:
    """Single non-streaming call to Ollama /api/chat."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": CONFIG.get("ollama", {}).get("keep_alive", "30m"),
    }
    if tools:
        payload["tools"] = tools
    if options:
        payload["options"] = options
    if format:
        payload["format"] = format
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t = timeout or CONFIG.get("ollama", {}).get("timeout", 1800)
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.load(r)


def _ollama_chat_stream(model: str, messages: list, tools: list = None,
                        options: dict = None, timeout: int = None):
    """Streaming call to Ollama /api/chat. Yields each NDJSON chunk dict."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": CONFIG.get("ollama", {}).get("keep_alive", "30m"),
    }
    if tools:
        payload["tools"] = tools
    if options:
        payload["options"] = options
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t = timeout or CONFIG.get("ollama", {}).get("timeout", 1800)
    with urllib.request.urlopen(req, timeout=t) as r:
        for raw in r:
            raw = raw.strip()
            if raw:
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue


def parse_text_tool_calls(content: str) -> list:
    """
    Fallback for models (notably qwen3-coder) that sometimes emit tool calls
    as text instead of native tool_calls. Returns a list in the same shape
    as Ollama's native tool_calls. Native calls always take precedence.

    Handles:
      <function=name><parameter=key>value</parameter>...</function>
      <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    """
    calls = []

    for m in re.finditer(r"<function=(\w+)>(.*?)</function>", content, re.S):
        name, body = m.group(1), m.group(2)
        args = {}
        for pm in re.finditer(r"<parameter=(\w+)>\s*(.*?)\s*</parameter>", body, re.S):
            val = pm.group(2)
            if re.fullmatch(r"-?\d+", val):
                val = int(val)
            args[pm.group(1)] = val
        calls.append({"function": {"name": name, "arguments": args}})

    if not calls:
        for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.S):
            try:
                obj = json.loads(m.group(1))
                calls.append({"function": {
                    "name": obj.get("name", ""),
                    "arguments": obj.get("arguments", {}) or {},
                }})
            except json.JSONDecodeError:
                continue

    return calls


class SubAgent:
    """Base class. Subclasses set NAME, SYSTEM_PROMPT, TOOLS, TOOL_FUNCTIONS."""

    NAME = "base"
    SYSTEM_PROMPT = "You are a helpful subagent."
    TOOLS: list = []
    TOOL_FUNCTIONS: dict = {}

    def __init__(self, model: str = None, max_turns: int = None, verbose: bool = True):
        cfg = subagent_config(self.NAME)
        self.model = model or cfg["model"]
        self.max_turns = max_turns or cfg["max_turns"]
        self.verbose = verbose

    def _log(self, msg: str):
        if self.verbose:
            print(f"[{self.NAME}] {msg}")

    def handle_tool_calls(self, tool_calls: list, messages: list):
        """Execute requested tools and append results to the conversation."""
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {}) or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            func = self.TOOL_FUNCTIONS.get(name)
            if func is None:
                result = {"success": False, "error": f"Unknown tool: {name}"}
            else:
                self._log(f"tool {name}({json.dumps(args)[:200]})")
                try:
                    result = func(**args)
                except Exception as e:
                    result = {"success": False, "error": str(e)}

            messages.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, default=str)[:8000],
            })

    def chat_with_tools(self, messages: list) -> str:
        """Autonomous tool-using loop using Ollama's native tool calling."""
        for turn in range(self.max_turns):
            resp = _ollama_chat(self.model, messages, tools=self.TOOLS or None)
            msg = resp.get("message", {})
            messages.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # Rescue tool calls the model wrote as text instead of natively
                tool_calls = parse_text_tool_calls(msg.get("content", ""))
                if tool_calls:
                    self._log("rescued text-format tool call(s)")
            if not tool_calls:
                return msg.get("content", "")

            self._log(f"turn {turn + 1}/{self.max_turns}: {len(tool_calls)} tool call(s)")
            self.handle_tool_calls(tool_calls, messages)

        return messages[-1].get("content", "") or "(max turns reached)"

    def run(self, prompt: str, context: str = None) -> str:
        """Entry point: run the subagent on a single task prompt."""
        messages = self._build_messages(prompt, context)
        self._log(f"model={self.model}")
        return self.chat_with_tools(messages)

    # ------------------ streaming ------------------

    def _build_messages(self, prompt: str, context: str = None) -> list:
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"Context:\n{context}"})
        messages.append({"role": "user", "content": prompt})
        return messages

    # A turn is a tool-call turn if its content begins with a text-format tool
    # call. We only need to peek at the lead to decide whether to suppress.
    _TOOL_LEAD = ("<function=", "<tool_call>", "<tool", "<|")

    def chat_with_tools_stream(self, messages: list):
        """
        Streaming tool loop. Yields event dicts:
          {"type":"token","text":...}     incremental final-answer text
          {"type":"tool","name":...,"args":...}
          {"type":"tool_result","name":...,"success":...}
          {"type":"final","content":...}  terminal event with the full answer
        Native tool-call turns (empty content) and text-format tool turns
        (content is the <function=...> block) are NOT streamed as tokens.
        """
        for turn in range(self.max_turns):
            buffer = ""
            decided = None          # None=undecided, "emit", or "suppress"
            native_calls = None
            emitted = ""

            for chunk in _ollama_chat_stream(self.model, messages,
                                             tools=self.TOOLS or None):
                msg = chunk.get("message", {})
                if msg.get("tool_calls"):
                    native_calls = (native_calls or []) + msg["tool_calls"]
                delta = msg.get("content", "")
                if delta:
                    buffer += delta
                    if decided is None:
                        lead = buffer.lstrip()
                        if any(lead.startswith(p) for p in self._TOOL_LEAD) \
                                or native_calls:
                            decided = "suppress"
                        elif len(lead) >= 16 or "\n" in lead:
                            decided = "emit"
                            yield {"type": "token", "text": buffer}
                            emitted = buffer
                    elif decided == "emit":
                        yield {"type": "token", "text": delta}
                        emitted += delta
                if chunk.get("done"):
                    break

            messages.append({"role": "assistant", "content": buffer,
                             "tool_calls": native_calls})

            tool_calls = native_calls
            if not tool_calls:
                tool_calls = parse_text_tool_calls(buffer)
                if tool_calls:
                    self._log("rescued text-format tool call(s)")

            if not tool_calls:
                # Final answer. Flush anything we buffered but hadn't emitted
                # (short answers that never crossed the decision threshold).
                if decided != "emit" and buffer:
                    yield {"type": "token", "text": buffer}
                elif buffer and len(buffer) > len(emitted):
                    yield {"type": "token", "text": buffer[len(emitted):]}
                yield {"type": "final", "content": buffer}
                return

            self._log(f"turn {turn + 1}/{self.max_turns}: "
                      f"{len(tool_calls)} tool call(s)")
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                yield {"type": "tool", "name": name, "args": args}
                func = self.TOOL_FUNCTIONS.get(name)
                if func is None:
                    result = {"success": False, "error": f"Unknown tool: {name}"}
                else:
                    try:
                        result = func(**args)
                    except Exception as e:
                        result = {"success": False, "error": str(e)}
                yield {"type": "tool_result", "name": name,
                       "success": bool(result.get("success", True))}
                messages.append({"role": "tool", "name": name,
                                 "content": json.dumps(result, default=str)[:8000]})

        yield {"type": "final", "content": messages[-1].get("content", "")
               or "(max turns reached)"}

    def run_stream(self, prompt: str, context: str = None):
        """Streaming entry point. Yields the event dicts from the tool loop."""
        messages = self._build_messages(prompt, context)
        self._log(f"model={self.model} [stream]")
        yield from self.chat_with_tools_stream(messages)
