"""
subagents/transcribe.py — audio/video transcription subagent.

Transcription itself is done locally with faster-whisper (preferred) or
openai-whisper if installed; the LLM is only used to clean up / summarize
the transcript when asked.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subagents.base import SubAgent  # noqa: E402
from tools.terminal import RUN_TERMINAL_TOOL, run_terminal  # noqa: E402

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".oga", ".flac", ".mp4", ".mkv", ".webm"}


def transcribe_file(path: str, language: str = None) -> dict:
    """Transcribe an audio/video file using a local Whisper backend."""
    if not os.path.exists(path):
        return {"success": False, "error": f"File not found: {path}"}
    if os.path.splitext(path)[1].lower() not in AUDIO_EXTS:
        return {"success": False, "error": f"Unsupported extension: {path}"}

    # Backend 1: faster-whisper (CTranslate2). GPU first, CPU fallback —
    # CUDA needs the cuBLAS 12 runtime which this box may not have.
    try:
        from faster_whisper import WhisperModel
        last_err = None
        for device, compute in (("auto", "auto"), ("cpu", "int8")):
            try:
                model = WhisperModel("base", device=device, compute_type=compute)
                segments, info = model.transcribe(path, language=language)
                text = " ".join(s.text.strip() for s in segments)
                return {"success": True, "backend": f"faster-whisper ({device})",
                        "language": info.language, "text": text}
            except Exception as e:
                last_err = e
        return {"success": False, "backend": "faster-whisper", "error": str(last_err)}
    except ImportError:
        pass

    # Backend 2: openai-whisper
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(path, language=language)
        return {"success": True, "backend": "openai-whisper",
                "language": result.get("language"), "text": result.get("text", "").strip()}
    except ImportError:
        return {"success": False, "error":
                "No Whisper backend installed. Run: pip install faster-whisper"}
    except Exception as e:
        return {"success": False, "backend": "openai-whisper", "error": str(e)}


TRANSCRIBE_TOOLS = [
    {"type": "function", "function": {
        "name": "transcribe_file",
        "description": "Transcribe a local audio or video file to text using Whisper.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path to the audio/video file"},
            "language": {"type": "string", "description": "ISO language code hint, e.g. 'en', 'no' (optional)"},
        }, "required": ["path"]}}},
    RUN_TERMINAL_TOOL,
]


class TranscribeAgent(SubAgent):
    NAME = "transcribe"
    TOOLS = TRANSCRIBE_TOOLS
    TOOL_FUNCTIONS = {
        "transcribe_file": transcribe_file,
        "run_terminal": run_terminal,
    }
    SYSTEM_PROMPT = (
        "You are TRANSCRIBE, a subagent of LARRY G-FORCE. Given an audio or "
        "video file, call transcribe_file, then return the transcript. If the "
        "user asks for a summary or cleanup, do that to the transcript text. "
        "Use run_terminal only to locate files."
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(TranscribeAgent().run(" ".join(sys.argv[1:])))
    else:
        print("usage: python transcribe.py <task, e.g. 'transcribe C:\\path\\to\\voice.ogg'>")
