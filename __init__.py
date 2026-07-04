"""Subagents of LARRY G-FORCE. Each runs an autonomous Ollama tool loop."""

from subagents.executor import ExecutorAgent
from subagents.editor import EditorAgent
from subagents.searcher import SearcherAgent
from subagents.transcribe import TranscribeAgent
from subagents.debugger import DebuggerAgent

SUBAGENTS = {
    "executor": ExecutorAgent,
    "editor": EditorAgent,
    "searcher": SearcherAgent,
    "transcribe": TranscribeAgent,
    "debugger": DebuggerAgent,
}

__all__ = ["ExecutorAgent", "EditorAgent", "SearcherAgent",
           "TranscribeAgent", "DebuggerAgent", "SUBAGENTS"]
