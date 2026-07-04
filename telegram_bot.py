#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  🤖 Local Larry - Telegram Bot Interface                                  ║
║  ═══════════════════════════════════════════════════════════════════════  ║
║  Enables conversations with local AI models via Telegram                  ║
║  Features: Multi-model routing, File browsing, MCP tools, RAG memory     ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import logging
import threading
import json
from pathlib import Path
from datetime import datetime
from collections import deque
from typing import Dict, Deque, List, Optional, Tuple
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()

import requests

# ═══════════════════════════════════════════════════════════════════════════
# 🎨 TERMINAL COLORS & STYLING
# ═══════════════════════════════════════════════════════════════════════════

class Colors:
    """ANSI color codes for terminal output."""
    # Basic Colors
    BLACK = '\033[30m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    # Styles
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    
    # Background
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # Reset
    END = '\033[0m'
    
    @classmethod
    def gradient(cls, text: str, colors: list) -> str:
        """Apply gradient colors to text."""
        result = ""
        for i, char in enumerate(text):
            color = colors[i % len(colors)]
            result += f"{color}{char}"
        return result + cls.END


class Spinner:
    """Animated spinner for loading states."""
    FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    DOTS = ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
    ARROWS = ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙']
    PULSE = ['█', '▓', '▒', '░', '▒', '▓']
    
    def __init__(self, message: str = "Loading", style: str = "dots"):
        self.message = message
        self.frames = getattr(self, style.upper(), self.DOTS)
        self.running = False
        self.thread = None
        self.idx = 0
    
    def spin(self):
        while self.running:
            frame = self.frames[self.idx % len(self.frames)]
            print(f"\r{Colors.CYAN}{frame}{Colors.END} {self.message}...", end="", flush=True)
            self.idx += 1
            time.sleep(0.1)
    
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()
    
    def stop(self, final_message: str = None):
        self.running = False
        if self.thread:
            self.thread.join(timeout=0.5)
        if final_message:
            print(f"\r{Colors.GREEN}✓{Colors.END} {final_message}" + " " * 20)
        else:
            print("\r" + " " * 50 + "\r", end="")


def print_banner():
    """Print stylish startup banner."""
    banner = (
        f"\n{Colors.CYAN}{Colors.BOLD}\n"
        r"  _                     _   _                          " + "\n"
        r" | |    ___   ___ __ _ | | | | __ _ _ __ _ __ _   _    " + "\n"
        r" | |   / _ \ / __/ _` || | | |/ _` | '__| '__| | | |   " + "\n"
        r" | |__| (_) | (_| (_| || | | | (_| | |  | |  | |_| |   " + "\n"
        r" |_____\___/ \___\__,_||_| |_|\__,_|_|  |_|   \__, |   " + "\n"
        r"                                              |___/    " + "\n"
        f"{Colors.END}"
    )
    banner = banner + f"""
{Colors.YELLOW}    ═══════════════════════════════════════════{Colors.END}
{Colors.WHITE}    ⚡ LARRY G-FORCE • TELEGRAM UPLINK ⚡{Colors.END}
{Colors.YELLOW}    ═══════════════════════════════════════════{Colors.END}
"""
    print(banner)


def print_section(title: str, icon: str = "📌"):
    """Print a styled section header."""
    line = "─" * (50 - len(title))
    print(f"\n{Colors.CYAN}{icon} {Colors.BOLD}{title}{Colors.END} {Colors.DIM}{line}{Colors.END}")


def print_status(message: str, status: str = "info"):
    """Print a styled status message."""
    icons = {
        "ok": f"{Colors.GREEN}✓{Colors.END}",
        "success": f"{Colors.GREEN}✓{Colors.END}",
        "fail": f"{Colors.RED}✗{Colors.END}",
        "error": f"{Colors.RED}✗{Colors.END}",
        "warn": f"{Colors.YELLOW}⚠{Colors.END}",
        "warning": f"{Colors.YELLOW}⚠{Colors.END}",
        "info": f"{Colors.BLUE}ℹ{Colors.END}",
        "run": f"{Colors.MAGENTA}▶{Colors.END}",
        "wait": f"{Colors.YELLOW}◌{Colors.END}",
    }
    icon = icons.get(status, icons["info"])
    print(f"{icon} {message}")


# ═══════════════════════════════════════════════════════════════════════════
# 📦 IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
from dataclasses import dataclass, field

from model_router import ModelRouter, TaskType, get_router, list_models
from file_browser import FileBrowser, get_browser
from kali_tools import TOOLS, list_tools, tool_help, run_tool_background, parse_args_with_preset
from activity_stream import ActivityStream

# G-FORCE: EnhancedAgent + HW_PROFILES
try:
    from agent_v2 import EnhancedAgent, HW_PROFILES
    ENHANCED_AGENT_AVAILABLE = True
except ImportError:
    EnhancedAgent = None
    HW_PROFILES = {"SPEED": {"num_gpu": 0, "num_ctx": 16384}, "ACCURACY": {"num_gpu": 0, "num_ctx": 65536}}
    ENHANCED_AGENT_AVAILABLE = False

# Skill Manager
try:
    from skill_manager import get_skill_manager
    SKILL_MANAGER_AVAILABLE = True
except ImportError:
    get_skill_manager = None
    SKILL_MANAGER_AVAILABLE = False

# Optional imports with fallbacks
try:
    from context_manager import ContextManager, get_context_manager
    CONTEXT_MANAGER_AVAILABLE = True
except ImportError:
    CONTEXT_MANAGER_AVAILABLE = False

try:
    from mcp_client import MCPToolkit, get_mcp_toolkit
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Real MCP host (Option A): Ollama + LocalLarry-Agentic driving true MCP stdio servers.
# The mcp_host package lives at the repo root (parent of src/), so make sure
# the root is importable regardless of how the bot was launched.
try:
    _REPO_ROOT = str(Path(__file__).resolve().parent.parent)
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)
    from mcp_host import MCPRunner
    MCP_HOST_AVAILABLE = True
except Exception as _mcp_host_err:  # broad: import drags in mcp SDK + openai
    MCPRunner = None
    MCP_HOST_AVAILABLE = False
    _MCP_HOST_IMPORT_ERROR = _mcp_host_err

# Production RAG (preferred)
try:
    from production_rag import ProductionRAG, get_rag
    PRODUCTION_RAG_AVAILABLE = True
except ImportError:
    ProductionRAG = get_rag = None
    PRODUCTION_RAG_AVAILABLE = False

# Legacy RAG Memory
try:
    from rag_integration import RAGManager, get_rag_manager
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False

# Voice Integration
try:
    from voice_module import VoiceManager, get_voice_manager
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

# Safe Code Executor
try:
    from safe_code_executor import get_executor
    CODE_EXECUTOR_AVAILABLE = True
except ImportError:
    get_executor = None
    CODE_EXECUTOR_AVAILABLE = False
try:
    from safe_code_executor import DebugHelper
except ImportError:
    DebugHelper = None

# Universal File Handler
try:
    from universal_file_handler import get_file_handler
    FILE_HANDLER_AVAILABLE = True
except ImportError:
    get_file_handler = None
    FILE_HANDLER_AVAILABLE = False

# Cross-Platform Paths
try:
    from cross_platform_paths import CrossPlatformPathManager
    CROSS_PLATFORM_PATHS_AVAILABLE = True
except ImportError:
    CrossPlatformPathManager = None
    CROSS_PLATFORM_PATHS_AVAILABLE = False

# Hardware Profile Manager
try:
    from hardware_profiles import ProfileManager, get_profile_manager
    PROFILE_MANAGER_AVAILABLE = True
except ImportError:
    ProfileManager = get_profile_manager = None
    PROFILE_MANAGER_AVAILABLE = False

# Token Manager
try:
    from token_manager import TokenManager
    TOKEN_MANAGER_AVAILABLE = True
except ImportError:
    TokenManager = None
    TOKEN_MANAGER_AVAILABLE = False

# Unified Context Manager
try:
    from unified_context_manager import UnifiedContextManager
    UNIFIED_CONTEXT_AVAILABLE = True
except ImportError:
    UnifiedContextManager = None
    UNIFIED_CONTEXT_AVAILABLE = False

# Sandbox Manager
try:
    from sandbox_manager import SandboxManager, get_sandbox_manager
    SANDBOX_AVAILABLE = True
except ImportError:
    SandboxManager = get_sandbox_manager = None
    SANDBOX_AVAILABLE = False

# Web Tools
try:
    from web_tools import WebScraper, YouTubeSummarizer, get_web_scraper, get_youtube_summarizer
    WEB_TOOLS_AVAILABLE = True
except ImportError:
    WebScraper = YouTubeSummarizer = get_web_scraper = get_youtube_summarizer = None
    WEB_TOOLS_AVAILABLE = False

# ===================== PRODUCTION LOGGING =====================
import logging.handlers

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(console_handler)

# Rotating file log (production)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "telegram_bot.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
logger.addHandler(file_handler)

# Also capture warnings
logging.captureWarnings(True)
# ========================================================


@dataclass
class ConversationContext:
    """Stores conversation context for a chat."""
    chat_id: int
    messages: List[Dict[str, str]] = field(default_factory=list)
    current_model: Optional[str] = None
    last_activity: datetime = field(default_factory=datetime.now)
    max_history: int = 20
    current_profile: str = "SPEED"
    current_skill: str = "DEFAULT"
    debug_mode: bool = False

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        self.last_activity = datetime.now()
        if len(self.messages) > self.max_history * 2:
            self.messages = self.messages[-self.max_history:]

    def get_context_prompt(self) -> str:
        if not self.messages:
            return ""
        return "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in self.messages[-self.max_history:]
        ])

    def clear(self):
        self.messages = []


class TelegramSessionManager:
    """
    Per-chat session + token manager for Telegram (Production Hardened).
    Goals:
    - Prevent infinite loops / repeated heavy requests
    - Track token usage per chat session
    - Prevent Telegram and main CLI from hammering the same heavy model simultaneously
    - Support very long user prompts (thousands of lines) by accumulating multi-message input
    - Provide clean session isolation + audit trail
    """

    def __init__(self, max_tokens_per_session: int = 48000):
        self.sessions: Dict[int, dict] = {}
        self.max_tokens = max_tokens_per_session
        self.active_heavy_tasks: set = set()
        self.recent_queries: Dict[int, list] = {}

    def get_session(self, chat_id: int) -> dict:
        if chat_id not in self.sessions:
            self.sessions[chat_id] = {
                "tokens_used": 0,
                "last_model": None,
                "active_task": None,
                "loop_count": 0,
                "last_queries": [],
                # === Long Prompt Builder State (for 1000+ line prompts) ===
                "prompt_building": False,
                "prompt_buffer": [],           # list of text chunks
                "prompt_started_at": None,
                "prompt_meta": {},             # e.g. {"purpose": "training", "tags": [...]}
            }
        return self.sessions[chat_id]

    def start_heavy_task(self, chat_id: int, task_description: str) -> bool:
        """Returns False if we should block this heavy task right now."""
        sess = self.get_session(chat_id)

        # Prevent two heavy tasks from same chat at once
        if chat_id in self.active_heavy_tasks:
            return False

        # Simple loop detection
        recent = sess["last_queries"]
        if task_description and any(q and task_description[:60] in q for q in recent[-3:]):
            sess["loop_count"] += 1
            if sess["loop_count"] >= 2:
                return False  # Block repeated similar heavy requests

        self.active_heavy_tasks.add(chat_id)
        sess["active_task"] = task_description[:120]
        sess["last_queries"].append(task_description[:80])
        if len(sess["last_queries"]) > 6:
            sess["last_queries"].pop(0)
        return True

    def end_heavy_task(self, chat_id: int):
        self.active_heavy_tasks.discard(chat_id)
        sess = self.get_session(chat_id)
        sess["active_task"] = None
        sess["loop_count"] = 0

    def add_tokens(self, chat_id: int, tokens: int):
        sess = self.get_session(chat_id)
        sess["tokens_used"] += tokens
        if sess["tokens_used"] > self.max_tokens:
            # Soft warning - we don't hard kill, just note it
            logger.warning(f"[TelegramSession] Chat {chat_id} exceeded soft token limit")

    def is_heavy_model_in_use(self) -> bool:
        """Simple global guard — can be made smarter later with ollama ps."""
        return len(self.active_heavy_tasks) > 0

    # ===================== LONG PROMPT BUILDER =====================
    def start_prompt_collection(self, chat_id: int, meta: dict = None) -> bool:
        sess = self.get_session(chat_id)
        if sess["prompt_building"]:
            return False
        sess["prompt_building"] = True
        sess["prompt_buffer"] = []
        sess["prompt_started_at"] = datetime.now()
        sess["prompt_meta"] = meta or {}
        return True

    def add_prompt_part(self, chat_id: int, text: str) -> bool:
        sess = self.get_session(chat_id)
        if not sess["prompt_building"]:
            return False
        sess["prompt_buffer"].append(text)
        return True

    def finish_prompt_collection(self, chat_id: int) -> Optional[str]:
        """Returns the full concatenated prompt as ONE clean string, or None if not building."""
        sess = self.get_session(chat_id)
        if not sess["prompt_building"]:
            return None

        full_prompt = "\n".join(sess["prompt_buffer"]).strip()
        # Clean up state
        sess["prompt_building"] = False
        buffer_len = len(sess["prompt_buffer"])
        sess["prompt_buffer"] = []
        sess["prompt_started_at"] = None
        meta = sess["prompt_meta"]
        sess["prompt_meta"] = {}

        # Track rough token usage
        self.add_tokens(chat_id, len(full_prompt) // 3)

        logger.info(f"[Telegram] Long prompt submitted for chat {chat_id} "
                    f"({buffer_len} parts, ~{len(full_prompt)} chars, meta={meta})")

        return full_prompt

    def cancel_prompt_collection(self, chat_id: int):
        sess = self.get_session(chat_id)
        sess["prompt_building"] = False
        sess["prompt_buffer"] = []
        sess["prompt_started_at"] = None
        sess["prompt_meta"] = {}

    def get_status(self, chat_id: int) -> str:
        sess = self.get_session(chat_id)
        active = "Yes" if chat_id in self.active_heavy_tasks else "No"
        building = f" (building long prompt: {len(sess['prompt_buffer'])} parts)" if sess["prompt_building"] else ""
        return (f"Tokens used: {sess['tokens_used']:,} | "
                f"Active heavy task: {active}{building} | "
                f"Recent queries tracked: {len(sess['last_queries'])}")


class TelegramBot:
    """Telegram Bot for AI conversations."""

    def __init__(self, bot_token: str = None):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")

        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.router = get_router()
        self.conversations: Dict[int, ConversationContext] = {}
        self.last_update_id = 0
        self.running = False

        # New: Session + token + heavy-task guard for Telegram
        self.session_mgr = TelegramSessionManager(max_tokens_per_session=48000)

        # Per-chat cancellation events for the kill-switch (/stop, /help stop).
        # A running /agent thread holds an event here and aborts when it is set.
        self._task_cancels: Dict[int, threading.Event] = {}

        # Skip the Telegram backlog on startup so we don't replay old messages
        # accumulated while the bot was offline. Disable with TELEGRAM_SKIP_PENDING=false.
        self.skip_pending = os.getenv("TELEGRAM_SKIP_PENDING", "true").lower() in ("true", "1", "yes", "on")

        # Load telegram default model from larry_config.json
        self.default_model = None
        try:
            import json
            config_path = os.path.join(os.path.dirname(__file__), "config", "larry_config.json")
            with open(config_path) as f:
                larry_cfg = json.load(f)
            self.default_model = larry_cfg.get("ollama", {}).get("telegram_default_model")
            if self.default_model:
                logger.info(f"Telegram default model from config: {self.default_model}")
        except Exception as e:
            logger.warning(f"Could not load larry_config.json: {e}")
        
        allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS")
        self.allowed_chat_ids = self._parse_chat_ids(allowed) or None
        self.admin_chat_ids = self._parse_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", ""))
        self.allow_all = os.getenv("TELEGRAM_ALLOW_ALL", "false").lower() in ("true", "1", "yes", "on")
        
        self.commands = {
            "/start": self.cmd_start,
            "/help": self.cmd_help,
            "/models": self.cmd_models,
            "/model": self.cmd_set_model,
            "/clear": self.cmd_clear,
            "/status": self.cmd_status,
            "/task": self.cmd_task,
            # Emergency kill-switch — stop every running/live task immediately.
            "/stop": self.cmd_stop,
            "/cancel": self.cmd_stop,
            "/abort": self.cmd_stop,
            "/killall": self.cmd_stop,
            "/panic": self.cmd_stop,
            "/ls": self.cmd_ls,
            "/cat": self.cmd_cat,
            "/cd": self.cmd_cd,
            "/edit": self.cmd_edit,
            "/run": self.cmd_run,
            "/find": self.cmd_find,
            "/grep": self.cmd_grep,
            "/rag": self.cmd_rag,
            "/index": self.cmd_index,
            "/search": self.cmd_search,
            "/voice": self.cmd_voice,
            "/speak": self.cmd_speak,
            "/kali": self.cmd_kali,
            "/tools": self.cmd_tools,
            "/nmap": self.cmd_nmap,
            "/nikto": self.cmd_nikto,
            "/whatweb": self.cmd_whatweb,
            "/whois": self.cmd_whois,
            "/dig": self.cmd_dig,
            "/enum4linux": self.cmd_enum4linux,
            # G-FORCE extended commands
            "/profile": self.cmd_profile,
            "/debug": self.cmd_debug,
            "/ragconfig": self.cmd_ragconfig,
            "/tokens": self.cmd_tokens,
            "/session": self.cmd_session,   # Session + token + heavy task guard status
            "/longprompt": self.cmd_longprompt,
            "/submit": self.cmd_submit_prompt,
            "/cancelprompt": self.cmd_cancel_prompt,
            "/health": self.cmd_health,
            "/skill": self.cmd_skill,
            "/sandbox": self.cmd_sandbox,
            "/web": self.cmd_web,
            "/search_web": self.cmd_search_web,
            "/youtube": self.cmd_youtube,
            "/agent": self.cmd_agent,
            "/solve": self.cmd_agent,
            # Real MCP host (Option A): LocalLarry-Agentic + true MCP stdio tools
            "/mcp": self.cmd_mcp,
            "/m": self.cmd_mcp,
            "/mcptools": self.cmd_mcptools,
            "/ports": self.cmd_ports,
            "/listeners": self.cmd_listeners,
            "/netscan": self.cmd_netscan,
            "/threats": self.cmd_threats,
            "/devices": self.cmd_devices,
            "/newdevices": self.cmd_newdevices,
            "/devicelog": self.cmd_devicelog,
            "/inbound": self.cmd_inbound,
            "/approve": self.cmd_approve,
            "/block": self.cmd_block,
        }

        # Initialize EnhancedAgent (G-FORCE core)
        self.agent = None
        if ENHANCED_AGENT_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.agent = EnhancedAgent(working_dir=base)
                logger.info("EnhancedAgent (G-FORCE) initialized")
            except Exception as e:
                logger.warning(f"EnhancedAgent init failed: {e}")

        # Skill Manager
        self.skill_manager = get_skill_manager() if SKILL_MANAGER_AVAILABLE else None

        # Initialize file browser
        self.file_browser = get_browser()

        # Production RAG (preferred over legacy)
        self.production_rag = None
        if PRODUCTION_RAG_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.production_rag = get_rag(
                    chroma_path=os.path.join(base, "memory", "chroma_db"),
                    use_reranker=True
                )
                logger.info("Production RAG initialized")
            except Exception as e:
                logger.warning(f"Production RAG init failed: {e}")

        # Profile Manager
        self.profile_manager = None
        if PROFILE_MANAGER_AVAILABLE:
            try:
                base = os.path.dirname(os.path.abspath(__file__))
                self.profile_manager = get_profile_manager(
                    db_path=os.path.join(base, "data", "unified_context.db")
                )
            except Exception:
                pass

        # Token Manager
        self.token_manager = TokenManager() if TOKEN_MANAGER_AVAILABLE else None

        # Rate limiting (per-chat deque-based token bucket)
        self.rate_limit_max = int(os.getenv("TELEGRAM_RATE_LIMIT_MAX", "12"))
        self.rate_limit_window = int(os.getenv("TELEGRAM_RATE_LIMIT_WINDOW", "60"))
        self._rate_limit: Dict[int, Deque[float]] = {}

        # Path sanitization base
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self.max_input_chars = 8000
        
        # Initialize context manager if available
        self.context_manager = None
        if CONTEXT_MANAGER_AVAILABLE:
            try:
                self.context_manager = get_context_manager(self.router)
            except Exception as e:
                logger.warning(f"Context manager init failed: {e}")
        
        # Initialize MCP toolkit if available
        self.mcp_toolkit = None
        if MCP_AVAILABLE:
            try:
                self.mcp_toolkit = get_mcp_toolkit()
            except Exception as e:
                logger.warning(f"MCP toolkit init failed: {e}")

        # Real MCP host (Option A): LocalLarry-Agentic driving true MCP stdio servers.
        # Spawning npx/uvx/RAG takes ~10-120s, so start it eagerly in the
        # background here — the runner owns its own thread + event loop and
        # signals ready when the servers are up. /mcp blocks until then.
        self.mcp_runner = None
        if MCP_HOST_AVAILABLE:
            try:
                self.mcp_runner = MCPRunner(model="LocalLarry-Agentic")
                logger.info("MCP host (Option A) starting in background…")
            except Exception as e:
                logger.warning(f"MCP host init failed: {e}")
        else:
            logger.info(
                f"MCP host (Option A) unavailable: {globals().get('_MCP_HOST_IMPORT_ERROR', 'not imported')}"
            )
        
        # Initialize RAG memory if available
        self.rag_manager = None
        if RAG_AVAILABLE:
            try:
                self.rag_manager = get_rag_manager()
                logger.info(f"✅ RAG memory initialized")
            except Exception as e:
                logger.warning(f"RAG manager init failed: {e}")
        
        # Initialize voice manager if available
        self.voice_manager = None
        if VOICE_AVAILABLE:
            try:
                self.voice_manager = get_voice_manager()
                logger.info(f"✅ Voice manager initialized")
            except Exception as e:
                logger.warning(f"Voice manager init failed: {e}")

        # Activity stream for dashboard
        self.activity = ActivityStream("telegram_bot")
        self.activity.emit(ActivityStream.SYSTEM, "Telegram bot initialized")

    def _api_call(self, method: str, data: dict = None, timeout: int = 30, retries: int = 3) -> dict:
        """Make API call with retry logic."""
        last_error = None
        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self.base_url}/{method}", 
                    json=data, 
                    timeout=timeout + 10  # Add buffer to timeout
                )
                return response.json()
            except requests.exceptions.ReadTimeout:
                last_error = "Read timeout - Telegram API slow to respond"
                logger.warning(f"Timeout on {method} (attempt {attempt + 1}/{retries})")
                time.sleep(2 ** attempt)  # Exponential backoff
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error (attempt {attempt + 1}/{retries}): {e}")
                time.sleep(2 ** attempt)
            except Exception as e:
                last_error = str(e)
                logger.error(f"API call failed: {e}")
                break
        return {"ok": False, "error": last_error}

    def send_message(self, chat_id: int, text: str) -> dict:
        if len(text) > 4000:
            parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for part in parts:
                self._api_call("sendMessage", {"chat_id": chat_id, "text": part})
                time.sleep(0.5)
            return {"ok": True}
        return self._api_call("sendMessage", {"chat_id": chat_id, "text": text})

    def send_typing(self, chat_id: int):
        self._api_call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    def get_updates(self, offset: int = None, timeout: int = 30) -> List[dict]:
        data = {"timeout": timeout}
        if offset:
            data["offset"] = offset
        # Use longer request timeout for long polling
        result = self._api_call("getUpdates", data, timeout=timeout + 15, retries=2)
        return result.get("result", []) if result.get("ok") else []

    _MAX_CONVERSATIONS = 500

    def get_conversation(self, chat_id: int) -> ConversationContext:
        if chat_id not in self.conversations:
            # Evict oldest entry if at capacity
            if len(self.conversations) >= self._MAX_CONVERSATIONS:
                oldest = next(iter(self.conversations))
                del self.conversations[oldest]
            self.conversations[chat_id] = ConversationContext(chat_id=chat_id)
        return self.conversations[chat_id]

    def is_allowed(self, chat_id: int) -> bool:
        if self.allow_all:
            return True
        if self.is_admin(chat_id):
            return True
        return self.allowed_chat_ids is None or chat_id in self.allowed_chat_ids

    def is_admin(self, chat_id: int) -> bool:
        return chat_id in self.admin_chat_ids

    @staticmethod
    def _parse_chat_ids(value: str) -> List[int]:
        result = []
        if not value:
            return result
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                logger.warning(f"Invalid chat id in env: {part}")
        return result

    def _parse_allowlist(self, value: str) -> List[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def cmd_start(self, chat_id: int, args: str) -> str:
        return """⚡ 𝗟𝗔𝗥𝗥𝗬 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗧𝗘𝗟𝗘𝗚𝗥𝗔𝗠 𝗨𝗣𝗟𝗜𝗡𝗞 ⚡
══════════════════════════════

🔥 Elite AI Operative Online.
🚀 Ready to execute.

💬 𝐂𝐎𝐌𝐌𝐀𝐍𝐃 𝐂𝐄𝐍𝐓𝐄𝐑
──────────────────────────────
/help      • Show this menu
/stop      • 🛑 STOP all running tasks (kill-switch)
/models    • List AI models 🤖
/model     • Switch model
/clear     • Clear history 🗑️
/status    • Show status 📊
/task      • Set task type

🎤 𝐕𝐨𝐢𝐜𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/voice     • Voice status 🎭
/speak     • Generate voice 🔊
🎙️ Send voice messages for STT!

📁 𝐅𝐢𝐥𝐞 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/ls        • List directory
/cd        • Change directory
/cat       • Read file 📄
/edit      • Write to file ✏️
/find      • Find files 🔍
/grep      • Search in files

🧠 𝐑𝐀𝐆 𝐌𝐞𝐦𝐨𝐫𝐲
───────────────────────────────────
/rag       • Memory status 📊
/index     • Index directory 📁
/search    • Search memory 🔍

🔴 𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲 𝐓𝐨𝐨𝐥𝐬
───────────────────────────────────
/tools     • List all tools 🗡️
/kali      • Run any tool
/nmap      • Port scan
/nikto     • Web vuln scan
/whatweb   • Tech fingerprint
/whois     • Domain lookup
/dig       • DNS query
/enum4linux • SMB enum

🛠️ 𝐒𝐲𝐬𝐭𝐞𝐦 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬
───────────────────────────────────
/run       • Execute command 💻

⚡ 𝐆-𝐅𝐎𝐑𝐂𝐄 𝐄𝐱𝐭𝐞𝐧𝐝𝐞𝐝
───────────────────────────────────
/profile   • Hardware profiles ⚡
/skill     • Switch AI persona 🎭
/debug     • Toggle RAG debug 🔍
/ragconfig • RAG configuration
/tokens    • Token counter 🔢
/session   • Session + safety status 🛡️
/longprompt • Start building a massive prompt (1000s of lines)
/submit     • Finish & process long prompt as one message
/sandbox   • Safe file editing 🧰
/agent     • Autonomous mode 🤖
/mcp       • Real MCP host (LocalLarry-Agentic + tools) 🧰
/mcptools  • MCP host status + tool list
/web       • Scrape webpage 🌐
/search_web • Web search
/youtube   • YouTube transcript 📺

🛡️ 𝐍𝐞𝐭𝐰𝐨𝐫𝐤 𝐒𝐞𝐜𝐮𝐫𝐢𝐭𝐲
───────────────────────────────────
/ports     • Open ports scan
/listeners • Listening services
/netscan   • Network summary
/threats   • Threat detection
/devices   • Network devices
/newdevices • New device alerts

✨ Just send a message or voice to start chatting!"""

    def cmd_help(self, chat_id: int, args: str) -> str:
        # Backdoor: `/help stop` (or kill/cancel/abort/panic) acts as an
        # emergency kill-switch that stops every running/live task.
        if args and args.strip().lower().split()[0] in ("stop", "kill", "cancel", "abort", "panic", "killall"):
            return self._stop_all_tasks(chat_id)
        return self.cmd_start(chat_id, args)

    def _stop_all_tasks(self, chat_id: int = None) -> str:
        """Emergency kill-switch: cancel every running heavy task and clear stuck state.

        Fired by /stop, /cancel, /abort, /killall, /panic, or `/help stop`.
        Cancels all in-flight /agent threads, clears the heavy-task guard for
        every chat, aborts any long-prompt builders, and kills background
        security-tool subprocesses (nmap/nikto/etc.).
        """
        # 1) Signal every cooperating /agent thread to abort at its next step.
        n_threads = 0
        for ev in list(self._task_cancels.values()):
            try:
                ev.set()
                n_threads += 1
            except Exception:
                pass

        # 2) Clear heavy-task guards + per-session running state across ALL chats,
        #    so loop guards reset and users aren't blocked from starting fresh work.
        n_heavy = len(self.session_mgr.active_heavy_tasks)
        self.session_mgr.active_heavy_tasks.clear()
        n_prompts = 0
        for sess in self.session_mgr.sessions.values():
            sess["active_task"] = None
            sess["loop_count"] = 0
            if sess.get("prompt_building"):
                n_prompts += 1
                sess["prompt_building"] = False
                sess["prompt_buffer"] = []
                sess["prompt_started_at"] = None
                sess["prompt_meta"] = {}

        # 3) Kill any running background security-tool subprocesses.
        n_tools = 0
        try:
            from kali_tools import kill_all_tools
            n_tools = kill_all_tools()
        except Exception as e:
            logger.debug(f"kill_all_tools failed: {e}")

        try:
            self._write_live_status()
        except Exception:
            pass

        logger.warning(
            f"[KILL-SWITCH] Stop-all triggered (chat={chat_id}): "
            f"{n_threads} agent thread(s), {n_heavy} heavy guard(s), "
            f"{n_prompts} prompt builder(s), {n_tools} tool process(es)"
        )

        return (
            "🛑 **EMERGENCY STOP**\n"
            "══════════════════════════════\n"
            f"• Agent tasks signalled to abort: {n_threads}\n"
            f"• Heavy-task guards cleared: {n_heavy}\n"
            f"• Long-prompt builders cancelled: {n_prompts}\n"
            f"• Background tool processes killed: {n_tools}\n"
            "• Loop guards reset.\n\n"
            "All live tasks have been stopped. Send a new message when ready."
        )

    def cmd_stop(self, chat_id: int, args: str) -> str:
        """Stop all running/live tasks (kill-switch)."""
        return self._stop_all_tasks(chat_id)

    def cmd_models(self, chat_id: int, args: str) -> str:
        models = self.router.available_models
        if not models:
            return "❌ No models available.\n\n💡 Is Ollama running?"
        output = ["⚡ 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗠𝗢𝗗𝗘𝗟 𝗔𝗥𝗦𝗘𝗡𝗔𝗟\n══════════════════════════════"]
        for i, model in enumerate(models[:15], 1):
            # Add icons based on model type
            icon = "🔵" if "llama" in model.lower() else "🟢" if "code" in model.lower() else "⚪"
            output.append(f"{icon} {i}. {model}")
        if len(models) > 15:
            output.append(f"\n📊 +{len(models) - 15} more models")
        output.append("\n💡 Use /model <name> to switch")
        return "\n".join(output)

    def cmd_set_model(self, chat_id: int, args: str) -> str:
        if not args:
            conv = self.get_conversation(chat_id)
            current = conv.current_model or "auto"
            return f"Current model: {current}\n\nUsage: /model <name>"
        if self.router.set_model(args.strip()):
            self.get_conversation(chat_id).current_model = args.strip()
            return f"✅ Switched to: {args.strip()}"
        return f"❌ Model '{args}' not available. Use /models"

    def cmd_clear(self, chat_id: int, args: str) -> str:
        self.get_conversation(chat_id).clear()
        return "🗑️ History cleared."

    def cmd_status(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        model = conv.current_model or "auto-routing"
        
        # Get context stats if available
        context_info = ""
        if self.context_manager:
            try:
                stats = self.context_manager.get_stats()
                context_info = f"\n🧠 Context   │ {stats.get('token_count', 0)} tokens"
            except:
                pass
        
        # Get voice stats if available
        voice_info = ""
        if self.voice_manager:
            try:
                vstats = self.voice_manager.get_status()
                if vstats.get('stt_available'):
                    voice_info += f"\n🎤 STT      │ ✅ {vstats.get('stt_model', 'N/A')}"
                if vstats.get('tts_available'):
                    voice_info += f"\n🔊 TTS      │ ✅ {vstats.get('tts_engine', 'N/A')}"
                    if vstats.get('voice_cloning'):
                        voice_info += " (Batman)"
            except:
                pass
        
        return f"""📊 𝗚-𝗙𝗢𝗥𝗖𝗘 𝗦𝗧𝗔𝗧𝗨𝗦
══════════════════════════════
🤖 Model     │ {model}
💬 Messages  │ {len(conv.messages)}
🔧 Available │ {len(self.router.available_models)} models
📁 Directory │ {self.file_browser.current_dir}{context_info}{voice_info}
══════════════════════════════
✅ Bot is running"""

    def cmd_task(self, chat_id: int, args: str) -> str:
        valid = [t.value for t in TaskType]
        if not args or args.strip().lower() not in valid:
            return f"Usage: /task <type>\nTypes: {', '.join(valid)}"
        task = TaskType(args.strip().lower())
        model, _ = self.router.get_model_for_task(task)
        self.get_conversation(chat_id).current_model = model
        return f"✅ Task: {task.value}\n🤖 Model: {model}"

    def cmd_ls(self, chat_id: int, args: str) -> str:
        try:
            return self.file_browser.ls(args.strip() if args else ".")
        except Exception as e:
            return f"❌ Error listing directory: {e}"

    def cmd_cat(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /cat <filepath>"
        try:
            return self.file_browser.read(args.strip())
        except Exception as e:
            return f"❌ Error reading file: {e}"

    def cmd_cd(self, chat_id: int, args: str) -> str:
        if not args:
            return f"📂 Current: {self.file_browser.pwd()}"
        try:
            result = self.file_browser.cd(args.strip())
            return result
        except Exception as e:
            return f"❌ Error changing directory: {e}"

    def cmd_edit(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /edit <filepath> <content>"
        try:
            parts = args.split(" ", 1)
            if len(parts) < 2:
                return "Usage: /edit <filepath> <content>"
            file_path, content = parts
            result = self.file_browser.write(file_path.strip(), content)
            return result
        except Exception as e:
            return f"❌ Error editing file: {e}"

    def cmd_run(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /run <command>"
        if not MCP_AVAILABLE or not self.mcp_toolkit:
            # Fallback to subprocess — shell=False to prevent injection
            try:
                import subprocess, shlex
                cmd_parts = shlex.split(args)
                if not cmd_parts:
                    return "❌ Empty command"
                result = subprocess.run(
                    cmd_parts, shell=False, capture_output=True, text=True, timeout=30
                )
                output = result.stdout or result.stderr or "(no output)"
                return f"📋 Output:\n{output[:3000]}"
            except subprocess.TimeoutExpired:
                return "❌ Command timed out (30s limit)"
            except Exception as e:
                return f"❌ Error: {e}"
        try:
            return self.mcp_toolkit.dispatch(f"/run {args}")
        except Exception as e:
            return f"❌ Error running command: {e}"

    def cmd_find(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /find <pattern> [path]"
        try:
            parts = args.split(" ", 1)
            pattern = parts[0]
            path = parts[1] if len(parts) > 1 else "."
            return self.file_browser.find(pattern, path)
        except Exception as e:
            return f"❌ Error finding files: {e}"

    def cmd_grep(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /grep <pattern> <path>"
        try:
            parts = args.split(" ", 1)
            if len(parts) < 2:
                return "Usage: /grep <pattern> <path>"
            pattern, path = parts
            return self.file_browser.grep(pattern.strip(), path.strip())
        except Exception as e:
            return f"❌ Error grepping files: {e}"
    
    def cmd_rag(self, chat_id: int, args: str) -> str:
        """Show RAG memory status and stats."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        try:
            stats = self.rag_manager.get_stats()
            if stats['status'] != 'active':
                return f"⚠️ RAG Status: {stats['status']}"
            
            output = ["🧠 𝗥𝗔𝗚 𝗠𝗲𝗺𝗼𝗿𝘆 𝗦𝘁𝗮𝘁𝘂𝘀", "══════════════════════════════"]
            
            for name, count in stats.get('collections', {}).items():
                icon = "📚" if count > 0 else "📭"
                output.append(f"{icon} {name}: {count}")
            
            output.append(f"\n📊 Total: {stats.get('total_documents', 0)} documents")
            output.append("\n💡 Commands: /index <dir>, /search <query>")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error getting RAG stats: {e}"
    
    def cmd_index(self, chat_id: int, args: str) -> str:
        """Index a directory into RAG memory."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        directory = args.strip() if args else "."
        
        try:
            result = self.rag_manager.index_directory(directory)
            count = result.get('indexed_count', 0)
            errors = result.get('errors', [])
            
            output = [f"📁 Indexed {count} files from {directory}"]
            if errors:
                output.append(f"⚠️ {len(errors)} errors occurred")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error indexing: {e}"
    
    def cmd_search(self, chat_id: int, args: str) -> str:
        """Search RAG memory."""
        if not self.rag_manager:
            return "❌ RAG memory not available"
        
        if not args:
            return "Usage: /search <query>"
        
        try:
            context = self.rag_manager.get_relevant_context(args, max_results=2)
            if not context:
                return "🔍 No relevant results found"
            
            # Truncate for Telegram
            if len(context) > 3000:
                context = context[:3000] + "\n\n... (truncated)"
            
            return f"🔍 𝗦𝗲𝗮𝗿𝗰𝗵 𝗥𝗲𝘀𝘂𝗹𝘁𝘀\n══════════════════════════════\n{context}"
        except Exception as e:
            return f"❌ Error searching: {e}"
    
    def cmd_voice(self, chat_id: int, args: str) -> str:
        """Show voice module status."""
        if not self.voice_manager:
            return "❌ Voice module not available"
        
        try:
            status = self.voice_manager.get_status()
            output = ["🎤 𝗩𝗼𝗶𝗰𝗲 𝗠𝗼𝗱𝘂𝗹𝗲 𝗦𝘁𝗮𝘁𝘂𝘀", "══════════════════════════════"]
            
            output.append(f"🗣️ STT: {'✅' if status['stt_available'] else '❌'} {status.get('stt_model', 'N/A')}")
            output.append(f"🔊 TTS: {'✅' if status['tts_available'] else '❌'} {status.get('tts_engine', 'N/A')}")
            output.append(f"🎭 Voice Cloning: {'✅' if status.get('voice_cloning') else '❌'}")
            output.append(f"📁 Voice Sample: {'✅' if status.get('voice_sample') else '❌'}")
            
            tasks = status.get('voice_tasks', [])
            output.append(f"🎯 Voice Tasks: {', '.join(tasks) if tasks else 'None'}")
            
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error getting voice status: {e}"
    
    def cmd_speak(self, chat_id: int, args: str) -> str:
        """Generate voice response for text."""
        if not self.voice_manager:
            return "❌ Voice module not available"
        
        if not args:
            return "Usage: /speak <text to speak>"
        
        try:
            # Generate voice
            audio_path = self.voice_manager.speak(args)
            
            # Send the audio file
            self.send_voice(chat_id, audio_path, caption=f"🎭 \"{args[:50]}{'...' if len(args) > 50 else ''}\"")
            
            return f"🎤 Voice generated and sent!"
        except Exception as e:
            return f"❌ Error generating voice: {e}"

    # ── Kali / Security commands ──────────────────────────────────────────

    def _run_tool_async(self, chat_id: int, tool_name: str, raw_args: str):
        """Run a tool in background and send result back to Telegram."""
        tool_obj = TOOLS.get(tool_name)
        if not tool_obj:
            self.send_message(chat_id, f"Unknown tool: {tool_name}")
            return

        expanded = parse_args_with_preset(tool_obj, raw_args)
        if expanded.startswith("__ERROR__"):
            self.send_message(chat_id, expanded[9:])
            return

        self.send_message(chat_id, f"Running: {tool_obj.cmd} {expanded}\nTimeout: {tool_obj.default_timeout}s ...")
        self.send_typing(chat_id)

        def on_done(success, output):
            header = f"[{tool_obj.cmd}] {'Done' if success else 'Finished'}\n{'=' * 30}\n"
            self.send_message(chat_id, header + output)

        run_tool_background(tool_name, expanded, callback=on_done, max_output=3500)

    def cmd_tools(self, chat_id: int, args: str) -> str:
        cat = args.strip() or None
        result = list_tools(cat)
        return result[:4000]

    def cmd_kali(self, chat_id: int, args: str) -> str:
        if not args:
            return ("Security Tools\n"
                    "/kali list [category]  — list tools\n"
                    "/kali help <tool>      — show presets\n"
                    "/kali <tool> [args]    — run tool\n"
                    "/kali <tool> :<preset> <target>\n\n"
                    "Shortcuts: /nmap /nikto /whatweb /whois /dig /enum4linux")
        parts = args.split(None, 1)
        sub = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "list":
            return list_tools(rest.strip() or None)[:4000]
        if sub == "help":
            return tool_help(rest.strip())
        # /kali <tool> [args]
        self._run_tool_async(chat_id, sub, rest)
        return ""  # response sent by callback

    def cmd_nmap(self, chat_id: int, args: str) -> str:
        if not args:
            return ("Usage: /nmap <target> [flags]\n"
                    "Presets: /nmap :quick <ip>  /nmap :service <ip>\n"
                    "         /nmap :full <ip>   /nmap :vuln <ip>\n"
                    "         /nmap :stealth <ip>")
        self._run_tool_async(chat_id, "nmap", args)
        return ""

    def cmd_nikto(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /nikto -h <target>\nPresets: /nikto :basic <url>  /nikto :fast <url>"
        self._run_tool_async(chat_id, "nikto", args)
        return ""

    def cmd_whatweb(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /whatweb <url>\nPresets: /whatweb :aggro <url>"
        self._run_tool_async(chat_id, "whatweb", args)
        return ""

    def cmd_whois(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /whois <domain or IP>"
        self._run_tool_async(chat_id, "whois", args)
        return ""

    def cmd_dig(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /dig <domain> [type]\nPresets: /dig :any <domain>  /dig :axfr <domain>"
        self._run_tool_async(chat_id, "dig", args)
        return ""

    def cmd_enum4linux(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /enum4linux <target>\nPresets: /enum4linux :all <ip>"
        self._run_tool_async(chat_id, "enum4linux", args)
        return ""

    # ═══════════════════════════════════════════════════════════════════════
    # G-FORCE EXTENDED COMMANDS
    # ═══════════════════════════════════════════════════════════════════════

    def _sanitize_path(self, path: str) -> str:
        """Prevent directory traversal attacks."""
        resolved = os.path.realpath(os.path.join(self._base_dir, path))
        if not resolved.startswith(self._base_dir):
            return None
        return resolved

    def _rate_limited(self, chat_id: int) -> bool:
        """Per-chat deque-based token bucket rate limiting."""
        now = time.time()
        bucket = self._rate_limit.setdefault(chat_id, deque())
        while bucket and now - bucket[0] > self.rate_limit_window:
            bucket.popleft()
        if len(bucket) >= self.rate_limit_max:
            return True
        bucket.append(now)
        return False

    def _estimate_tokens(self, text: str) -> int:
        if self.token_manager:
            return self.token_manager.count(text)
        return len(text) // 4

    def _chunk_and_summarize_long_prompt_sync(self, long_text: str) -> str:
        """
        Production feature for extremely long inputs (>50k tokens).
        Chunks the input and summarizes sections using a fast model so the main model isn't overwhelmed.
        """
        if not self.router or not getattr(self.router, 'available_models', None):
            return long_text[:180000]

        # Prefer small/fast models for summarization work
        fast = [m for m in self.router.available_models
                if any(k in m.lower() for k in ['phi', 'qwen', 'gemma', 'mistral', '3b', '7b', 'mini'])]
        model = fast[0] if fast else self.router.available_models[0]

        # Chunk roughly every 7-8k tokens
        chunks = []
        buf = []
        size = 0
        for line in long_text.splitlines():
            buf.append(line)
            size += len(line) + 1
            if size > 28000:
                chunks.append('\n'.join(buf))
                buf = []
                size = 0
        if buf:
            chunks.append('\n'.join(buf))

        summaries = []
        for i, ch in enumerate(chunks):
            p = f"Summarize this section. Keep ALL technical details, commands, facts, and user intent. Be concise but complete:\n\n{ch[:24000]}"
            try:
                s = self.router.generate(p, model=model)
                summaries.append(f"[Part {i+1}]\n{s}")
            except Exception:
                summaries.append(f"[Part {i+1} - truncated]\n{ch[:10000]}")

        final = "USER PROVIDED A VERY LONG PROMPT. INTELLIGENTLY SUMMARIZED VERSION:\n\n" + "\n\n".join(summaries)
        return final[:180000]

    def cmd_profile(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        if not args:
            info = f"Current: {conv.current_profile}\nAvailable: {', '.join(HW_PROFILES.keys())}"
            if self.profile_manager:
                try:
                    info = f"Current: {self.profile_manager.get_current_profile_name()}\nAvailable: {', '.join(self.profile_manager.list_profiles())}"
                except Exception:
                    pass
            return f"⚡ Hardware Profile\n{info}"
        name = args.strip().upper()
        if name in HW_PROFILES or (self.profile_manager and name in (self.profile_manager.list_profiles() if hasattr(self.profile_manager, 'list_profiles') else [])):
            conv.current_profile = name
            if self.profile_manager:
                try:
                    self.profile_manager.set_profile(name)
                except Exception:
                    pass
            return f"✅ Profile switched to {name}"
        return f"Unknown profile. Available: {', '.join(HW_PROFILES.keys())}"

    def cmd_debug(self, chat_id: int, args: str) -> str:
        conv = self.get_conversation(chat_id)
        conv.debug_mode = not conv.debug_mode
        return f"🔍 Debug mode: {'ON' if conv.debug_mode else 'OFF'}\nRAG verification will be {'shown' if conv.debug_mode else 'hidden'} in responses."

    def cmd_ragconfig(self, chat_id: int, args: str) -> str:
        parts = ["📊 RAG Configuration\n"]
        if self.production_rag:
            stats = self.production_rag.get_stats()
            parts.append(f"Backend: Production RAG")
            parts.append(f"Status: {stats.get('status', '?')}")
            parts.append(f"Reranker: {stats.get('reranker', '?')}")
            for name, count in stats.get("collections", {}).items():
                parts.append(f"  {name}: {count} docs")
        elif self.rag_manager:
            stats = self.rag_manager.get_stats()
            parts.append(f"Backend: Legacy RAG")
            parts.append(f"Total: {stats.get('total_documents', '?')} docs")
        else:
            parts.append("RAG: Not available")
        return "\n".join(parts)

    def cmd_session(self, chat_id: int, args: str) -> str:
        """Show Telegram session state, token usage, and safety guards."""
        status = self.session_mgr.get_status(chat_id)
        heavy = "🚨 Active heavy task(s)" if self.session_mgr.is_heavy_model_in_use() else "✅ No heavy tasks running"
        return (
            "🧠 **Telegram Session Status**\n"
            f"{status}\n"
            f"{heavy}\n\n"
            "Safeguards active:\n"
            "• Loop detection on repeated /agent requests\n"
            "• Prevents starting multiple heavy tasks from same chat\n"
            "• Soft token budget per session\n"
            "• Model contention warning when main agent is busy"
        )

    def cmd_longprompt(self, chat_id: int, args: str) -> str:
        """Start collecting a very long prompt (thousands of lines) from multiple messages or files."""
        meta = {"purpose": args.strip() or "general"} if args else {}
        if self.session_mgr.start_prompt_collection(chat_id, meta):
            return ("📝 **Long Prompt Mode Activated**\n\n"
                    "Send as many messages or documents as you want.\n"
                    "Everything will be concatenated into **one single prompt** when you finish.\n\n"
                    "When done: `/submit`\n"
                    "To cancel: `/cancelprompt`\n\n"
                    "Useful for: large training examples, custom system prompts, big context, codebases, etc.")
        return "⚠️ Already collecting a long prompt for this chat. Use /submit or /cancelprompt."

    def cmd_submit_prompt(self, chat_id: int, args: str) -> str:
        """Finish long prompt collection and process the full text as one prompt."""
        full_prompt = self.session_mgr.finish_prompt_collection(chat_id)
        if full_prompt is None:
            return "No long prompt is currently being built. Use /longprompt first."

        if len(full_prompt) < 10:
            return "Collected prompt is too short. Cancelled."

        # === PRODUCTION: Auto-save long prompt with metadata ===
        self._auto_save_long_prompt(chat_id, full_prompt)

        # Also update live status file for dashboard
        self._write_live_status()

        self.send_typing(chat_id)
        # Process as a normal (but very long) user message through the full agent pipeline
        try:
            response = self.process_message(chat_id, full_prompt)
            return response
        except Exception as e:
            logger.exception("Long prompt processing failed")
            return f"❌ Failed to process the long prompt: {e}"

    def cmd_cancel_prompt(self, chat_id: int, args: str) -> str:
        self.session_mgr.cancel_prompt_collection(chat_id)
        self._write_live_status()
        return "Long prompt collection cancelled."

    # ===================== PRODUCTION HELPERS =====================
    def _auto_save_long_prompt(self, chat_id: int, full_prompt: str):
        """Auto-save long prompts to personal_ai_training/data/long_prompts/ with rich metadata."""
        try:
            from datetime import datetime as dt
            import hashlib

            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            prompt_hash = hashlib.md5(full_prompt[:500].encode()).hexdigest()[:8]
            filename = f"long_prompt_{timestamp}_{chat_id}_{prompt_hash}.json"

            save_dir = Path(__file__).parent.parent / "personal_ai_training" / "data" / "long_prompts"
            save_dir.mkdir(parents=True, exist_ok=True)
            filepath = save_dir / filename

            meta = self.session_mgr.get_session(chat_id).get("prompt_meta", {})
            data = {
                "chat_id": chat_id,
                "timestamp": dt.now().isoformat(),
                "length_chars": len(full_prompt),
                "approx_tokens": len(full_prompt) // 4,
                "meta": meta,
                "prompt": full_prompt,
                "source": "telegram_long_prompt_builder"
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"[Production] Long prompt auto-saved: {filepath} ({len(full_prompt)} chars)")
        except Exception as e:
            logger.error(f"Failed to auto-save long prompt: {e}")

    def _write_live_status(self):
        """Write current session state for the dashboard to consume."""
        try:
            status = {
                "timestamp": datetime.now().isoformat(),
                "active_sessions": len(self.session_mgr.sessions),
                "heavy_tasks": list(self.session_mgr.active_heavy_tasks),
                "long_prompt_builders": {
                    cid: {
                        "parts": len(s.get("prompt_buffer", [])),
                        "started": str(s.get("prompt_started_at")),
                        "meta": s.get("prompt_meta", {})
                    }
                    for cid, s in self.session_mgr.sessions.items()
                    if s.get("prompt_building")
                },
                "heavy_task_details": {
                    cid: s.get("active_task")
                    for cid, s in self.session_mgr.sessions.items()
                    if cid in self.session_mgr.active_heavy_tasks
                }
            }

            # Repo-root logs (GITHUB/logs) — the same file dashboard_hub's
            # /api/telegram/status reads — so the Telegram Live Monitor panel
            # shows real state (src/logs is isolated from the dashboard).
            status_file = Path(__file__).resolve().parent.parent / "logs" / "telegram_live_status.json"
            status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to write live status: {e}")

    def cmd_health(self, chat_id: int, args: str) -> str:
        """Production health check for the bot and agent."""
        parts = ["🩺 **Bot Health Check**"]
        parts.append(f"• Telegram API: {'✅' if self.bot_token else '❌'}")
        parts.append(f"• Agent (agent_v2): {'✅' if self.agent else '❌'}")
        parts.append(f"• Session Manager: ✅ (active sessions: {len(self.session_mgr.sessions)})")
        parts.append(f"• Heavy tasks running: {len(self.session_mgr.active_heavy_tasks)}")
        parts.append(f"• RAG: {'✅' if (self.production_rag or self.rag_manager) else '❌'}")
        parts.append(f"• MCP Toolkit (legacy): {'✅' if self.mcp_toolkit else '❌'}")
        if self.mcp_runner:
            parts.append(f"• MCP Host (LocalLarry-Agentic): {self.mcp_runner.status_line()}")
        else:
            parts.append("• MCP Host (LocalLarry-Agentic): ❌")
        parts.append(f"• Voice: {'✅' if self.voice_manager else '❌'}")
        parts.append(f"• Uptime since last restart: running")
        return "\n".join(parts)

    def cmd_tokens(self, chat_id: int, args: str) -> str:
        if args:
            count = self._estimate_tokens(args)
            return f"🔢 Tokens in text: {count:,}"
        conv = self.get_conversation(chat_id)
        total = sum(self._estimate_tokens(m['content']) for m in conv.messages)
        return f"🔢 Conversation tokens: {total:,} ({len(conv.messages)} messages)"

    def cmd_skill(self, chat_id: int, args: str) -> str:
        if not self.skill_manager:
            return "⚠️ Skill Manager not available"
        conv = self.get_conversation(chat_id)
        if not args:
            skills = self.skill_manager.list_skills() if hasattr(self.skill_manager, 'list_skills') else []
            return f"🎯 Current: {conv.current_skill}\nAvailable: {', '.join(skills) if skills else 'DEFAULT'}"
        conv.current_skill = args.strip().upper()
        return f"✅ Skill set to: {conv.current_skill}"

    def cmd_sandbox(self, chat_id: int, args: str) -> str:
        if not self.agent or not self.agent.sandbox:
            return "⚠️ Sandbox Manager not available"
        if not args:
            return ("🧰 Sandbox Commands:\n"
                    "/sandbox stage <file> — Stage file\n"
                    "/sandbox edit <file> <content> — Edit\n"
                    "/sandbox test <file> — Test changes\n"
                    "/sandbox deploy <file> — Deploy\n"
                    "/sandbox rollback <file> — Rollback\n"
                    "/sandbox status — Show staged")
        parts = args.split(None, 2)
        sub = parts[0].lower()
        if sub == "stage" and len(parts) > 1:
            safe = self._sanitize_path(parts[1])
            if not safe:
                return "⚠️ Path outside allowed directory."
            return self.agent.sandbox_stage_file(safe)
        elif sub == "edit" and len(parts) > 2:
            safe = self._sanitize_path(parts[1])
            if not safe:
                return "⚠️ Path outside allowed directory."
            return self.agent.sandbox_edit_file(safe, parts[2])
        elif sub == "test" and len(parts) > 1:
            return self.agent.sandbox_test_changes(parts[1])
        elif sub == "deploy" and len(parts) > 1:
            return self.agent.sandbox_deploy(parts[1])
        elif sub == "rollback" and len(parts) > 1:
            return self.agent.sandbox_rollback(parts[1])
        elif sub == "status":
            return self.agent.get_sandbox_status()
        return "Usage: /sandbox <stage|edit|test|deploy|rollback|status> [args]"

    def cmd_web(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /web <url>"
        if self.agent:
            return self.agent.execute_web_command("web", args.split())
        return "⚠️ Web tools not available"

    def cmd_search_web(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /search_web <query>"
        if self.agent:
            return self.agent.execute_web_command("search_web", args.split())
        return "⚠️ Web search not available"

    def cmd_youtube(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /youtube <url> [summarize]"
        if self.agent:
            return self.agent.execute_web_command("youtube", args.split())
        return "⚠️ YouTube tools not available"

    def cmd_agent(self, chat_id: int, args: str) -> str:
        if not args:
            return "Usage: /agent <task description>\nRuns autonomous multi-step task solving."
        if not self.agent:
            return "⚠️ EnhancedAgent not available"

        task = args.strip()

        # === New safety layer ===
        if not self.session_mgr.start_heavy_task(chat_id, task):
            return ("⛔ Heavy task blocked.\n"
                    "• You already have an active agentic task running.\n"
                    "• Or you're repeating the same request too quickly (loop protection).\n"
                    "Use /clear or wait for current task to finish.")

        # Optional: global guard against using same heavy model as main CLI
        if self.session_mgr.is_heavy_model_in_use():
            # We still allow it, but we warn (user can decide)
            self.send_message(chat_id, "⚠️ Note: A heavy task appears active. Using same model may cause contention.")

        self.send_typing(chat_id)

        # Register a cancellation event so /stop (or /help stop) can abort this task.
        cancel = threading.Event()
        self._task_cancels[chat_id] = cancel

        def _run_agentic():
            import asyncio
            loop = asyncio.new_event_loop()
            def _feedback(msg):
                # Abort cooperatively the moment the kill-switch is fired.
                if cancel.is_set():
                    raise RuntimeError("__TASK_CANCELLED__")
                self.send_message(chat_id, f"🤖 {msg}")

            try:
                result = loop.run_until_complete(
                    self.agent.process_query_agentic(task, feedback_cb=_feedback)
                )
                if cancel.is_set():
                    self.send_message(chat_id, "🛑 Agent task stopped by kill-switch.")
                else:
                    self.send_message(chat_id, f"🤖 **Agent Result:**\n{result[:3800]}")
                    # Track rough token usage (very approximate)
                    self.session_mgr.add_tokens(chat_id, len(result) // 3 + len(task) // 3)
            except Exception as e:
                if cancel.is_set() or "__TASK_CANCELLED__" in str(e):
                    self.send_message(chat_id, "🛑 Agent task stopped by kill-switch.")
                else:
                    self.send_message(chat_id, f"❌ Agent error: {e}")
            finally:
                self.session_mgr.end_heavy_task(chat_id)
                self._task_cancels.pop(chat_id, None)
                self._write_live_status()
                loop.close()

        t = threading.Thread(target=_run_agentic, daemon=True)
        t.start()
        self._write_live_status()
        return f"🤖 Agent started on task: {task[:80]}...\nProgress updates will follow (heavy work — be patient)."

    # ── Real MCP Host (Option A: LocalLarry-Agentic + true MCP stdio tools) ──────
    def cmd_mcptools(self, chat_id: int, args: str) -> str:
        """Show the live MCP host status and the tools it has aggregated."""
        if not self.mcp_runner:
            return ("⚠️ MCP host not available.\n"
                    f"Reason: {globals().get('_MCP_HOST_IMPORT_ERROR', 'mcp_host import failed')}")
        lines = [self.mcp_runner.status_line()]
        if self.mcp_runner.ready:
            tools = self.mcp_runner.tool_names()
            lines.append("")
            lines.append("\n".join(f"• {t}" for t in tools))
        return "\n".join(lines)

    def cmd_mcp(self, chat_id: int, args: str) -> str:
        """Run a prompt through the real MCP host (LocalLarry-Agentic decides which
        MCP tools to call: filesystem, web fetch, RAG memory)."""
        if not self.mcp_runner:
            return ("⚠️ MCP host not available.\n"
                    f"Reason: {globals().get('_MCP_HOST_IMPORT_ERROR', 'mcp_host import failed')}")
        if not args or not args.strip():
            return ("Usage: /mcp <prompt>\n"
                    "Runs your prompt through LocalLarry-Agentic with real MCP tools "
                    "(filesystem, fetch, RAG). /mcptools shows status + tools.")

        if not self.mcp_runner.ready:
            # Don't block the polling loop; tell the user to retry shortly.
            return ("⏳ MCP host is still spawning its servers (first start can "
                    "take up to ~2 min for the RAG model load). Try again in a moment — "
                    "/mcptools shows when it's ready.")

        prompt = args.strip()

        # Reuse the same heavy-task guard as /agent so concurrent heavy work
        # and rapid-fire loops are blocked per chat.
        if not self.session_mgr.start_heavy_task(chat_id, f"mcp:{prompt}"):
            return ("⛔ MCP task blocked.\n"
                    "• You already have an active heavy task running, or\n"
                    "• you're repeating the same request too quickly (loop protection).\n"
                    "Use /clear or wait for the current task to finish.")

        self.send_typing(chat_id)

        # Register a cancellation event so /stop can abort.
        cancel = threading.Event()
        self._task_cancels[chat_id] = cancel

        conv = self.get_conversation(chat_id)
        # Pass prior turns as history (exclude the system prompt; the agent
        # builds its own). Keep it bounded.
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in conv.messages[-10:]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        def _run_mcp():
            try:
                result = self.mcp_runner.run_sync(prompt, history=history, timeout=300)
                if cancel.is_set():
                    self.send_message(chat_id, "🛑 MCP task stopped by kill-switch.")
                    return
                answer = result.answer or "(no answer produced)"
                # Surface which tools fired, like /agent's progress updates.
                if result.tool_calls_made:
                    used = ", ".join(
                        sorted({c["tool"] for c in result.tool_calls_made})
                    )
                    answer += f"\n\n🔧 tools used ({len(result.tool_calls_made)} call(s)): {used}"
                self.send_message(chat_id, f"🧰 **MCP:**\n{answer[:3800]}")
                # Record in conversation history for follow-ups.
                conv.add_message("user", prompt)
                conv.add_message("assistant", result.answer or "")
                self.session_mgr.add_tokens(chat_id, (len(answer) + len(prompt)) // 3)
            except Exception as e:
                if cancel.is_set():
                    self.send_message(chat_id, "🛑 MCP task stopped by kill-switch.")
                else:
                    self.send_message(chat_id, f"❌ MCP error: {e}")
            finally:
                self.session_mgr.end_heavy_task(chat_id)
                self._task_cancels.pop(chat_id, None)
                self._write_live_status()

        threading.Thread(target=_run_mcp, daemon=True).start()
        self._write_live_status()
        return f"🧰 MCP host working on: {prompt[:80]}…\n(LocalLarry-Agentic is choosing tools — reply will follow)"

    # ── Network Security Commands ─────────────────────────────────────
    def cmd_ports(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            ports = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    port = conn.laddr.port
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    risk = "🔴" if port < 1024 and port not in (22, 53, 80, 443) else "🟢"
                    ports.append(f"{risk} :{port} — {name} (PID {pid})")
            if not ports:
                return "🟢 No listening ports"
            return "🔍 Open Ports:\n" + "\n".join(ports[:30])
        except Exception as e:
            return f"❌ Port scan failed: {e}"

    def cmd_listeners(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            listeners = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "LISTEN" and conn.laddr:
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    addr = f"{conn.laddr.ip}:{conn.laddr.port}"
                    listeners.append(f"  {addr:25s} {name} (PID {pid})")
            return "📡 Listening Services:\n" + "\n".join(listeners[:30]) if listeners else "No listeners found."
        except Exception as e:
            return f"❌ {e}"

    def cmd_netscan(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            conns = psutil.net_connections(kind="inet")
            listen = len([c for c in conns if c.status == "LISTEN"])
            estab = len([c for c in conns if c.status == "ESTABLISHED"])
            total = len(conns)
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory().percent
            return (f"📊 Network Summary\n"
                    f"Total connections: {total}\n"
                    f"Listening: {listen}\n"
                    f"Established: {estab}\n"
                    f"CPU: {cpu:.0f}% | MEM: {mem:.0f}%")
        except Exception as e:
            return f"❌ {e}"

    def cmd_threats(self, chat_id: int, args: str) -> str:
        try:
            import psutil
            threats = []
            for proc in psutil.process_iter(["pid", "name", "connections", "cpu_percent"]):
                try:
                    info = proc.info
                    cpu = info.get("cpu_percent", 0) or 0
                    if cpu > 80:
                        threats.append(f"⚠️ High CPU: {info['name']} (PID {info['pid']}) at {cpu:.0f}%")
                except Exception:
                    pass
            # Check for unusual outbound connections
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr:
                    rport = conn.raddr.port
                    if rport in (4444, 5555, 6666, 6667, 31337):
                        threats.append(f"🔴 Suspicious port: :{rport} → {conn.raddr.ip}")
            if not threats:
                return "🟢 No threats detected"
            return "🚨 Threat Detection:\n" + "\n".join(threats[:20])
        except Exception as e:
            return f"❌ {e}"

    def cmd_devices(self, chat_id: int, args: str) -> str:
        if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
            try:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    return str(self.agent.mcp.network_monitor.get_devices())[:4000]
            except Exception:
                pass
        # Fallback: ARP table
        try:
            import subprocess
            r = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10)
            return f"📡 Network Devices (ARP):\n{r.stdout[:3000]}"
        except Exception as e:
            return f"❌ {e}"

    def cmd_newdevices(self, chat_id: int, args: str) -> str:
        if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
            try:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    return str(self.agent.mcp.network_monitor.get_new_devices())[:4000]
            except Exception:
                pass
        return "⚠️ Device tracking requires network_monitor (MCP toolkit)"

    def cmd_inbound(self, chat_id: int, args: str) -> str:
        """Show current inbound connections."""
        try:
            self.send_typing(chat_id)
            # Try MCP network_monitor first
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.get_inbound_connections()
                    if result.get('success'):
                        conns = result.get('connections', [])
                        if not conns:
                            return "✅ No inbound connections detected"
                        output = ["📥 *INBOUND CONNECTIONS*\n━━━━━━━━━━━━━━"]
                        for c in conns[:15]:
                            remote = c.get('remote_address', '?')
                            local_port = c.get('local_port', '?')
                            proc = c.get('process_name', 'unknown')[:15]
                            output.append(f"• `{remote}` → :{local_port} ({proc})")
                        if len(conns) > 15:
                            output.append(f"\n_...and {len(conns)-15} more_")
                        return "\n".join(output)
                    return f"❌ {result.get('error', 'Failed to get connections')}"
            # Fallback: psutil-based inbound detection
            import psutil
            inbound = []
            for conn in psutil.net_connections(kind="inet"):
                if conn.status == "ESTABLISHED" and conn.raddr and conn.laddr:
                    pid = conn.pid or 0
                    try:
                        name = psutil.Process(pid).name() if pid else "?"
                    except Exception:
                        name = "?"
                    inbound.append(f"• `{conn.raddr.ip}:{conn.raddr.port}` → :{conn.laddr.port} ({name})")
            if not inbound:
                return "✅ No inbound connections detected"
            return "📥 *INBOUND CONNECTIONS*\n━━━━━━━━━━━━━━\n" + "\n".join(inbound[:20])
        except Exception as e:
            return f"❌ Error getting inbound connections: {e}"

    def cmd_devicelog(self, chat_id: int, args: str) -> str:
        """Show device activity log."""
        try:
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    lines = int(args) if args and args.strip().isdigit() else 20
                    result = self.agent.mcp.network_monitor.get_device_log(lines=lines)
                    entries = result.get('entries', [])
                    if not entries:
                        return "📋 No device activity logged yet"
                    output = ["📋 *DEVICE ACTIVITY LOG*\n━━━━━━━━━━━━━━"]
                    output.append(f"Showing {len(entries)} of {result.get('total_entries', 0)} entries\n")
                    for entry in entries[-15:]:
                        if "NEW_DEVICE" in entry:
                            output.append(f"🆕 {entry}")
                        elif "BLOCKED" in entry:
                            output.append(f"🚫 {entry}")
                        elif "APPROVED" in entry:
                            output.append(f"✅ {entry}")
                        elif "IP_CHANGED" in entry:
                            output.append(f"🔄 {entry}")
                        else:
                            output.append(f"• {entry}")
                    return "\n".join(output)
            return "❌ Device log requires network_monitor (MCP toolkit)"
        except Exception as e:
            return f"❌ Error getting device log: {e}"

    def cmd_approve(self, chat_id: int, args: str) -> str:
        """Approve a device by MAC address."""
        try:
            if not args:
                return "Usage: `/approve <MAC> [name]`\nExample: `/approve AA-BB-CC-DD-EE-FF MyPhone`"
            if not self.is_admin(chat_id):
                return "⛔ Admin access required for device approval"
            parts = args.split(maxsplit=1)
            mac = parts[0].upper()
            name = parts[1] if len(parts) > 1 else ""
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.approve_device(mac=mac, name=name)
                    if result.get('success'):
                        return f"✅ *Device Approved*\nMAC: `{result.get('mac')}`\nName: `{result.get('name')}`"
                    return f"❌ {result.get('error', 'Failed to approve device')}"
            return "❌ Network monitor not available"
        except Exception as e:
            return f"❌ Error approving device: {e}"

    def cmd_block(self, chat_id: int, args: str) -> str:
        """Block a device by MAC address."""
        try:
            if not args:
                return "Usage: `/block <MAC> [reason]`\nExample: `/block AA-BB-CC-DD-EE-FF Suspicious device`"
            if not self.is_admin(chat_id):
                return "⛔ Admin access required for device blocking"
            parts = args.split(maxsplit=1)
            mac = parts[0].upper()
            reason = parts[1] if len(parts) > 1 else "Manual block"
            self.send_typing(chat_id)
            if self.agent and hasattr(self.agent, 'mcp') and self.agent.mcp:
                if hasattr(self.agent.mcp, 'network_monitor'):
                    result = self.agent.mcp.network_monitor.block_device(mac=mac, reason=reason)
                    if result.get('success'):
                        return f"🚫 *Device Blocked*\nMAC: `{result.get('mac')}`\nReason: `{result.get('reason')}`"
                    return f"❌ {result.get('error', 'Failed to block device')}"
            return "❌ Network monitor not available"
        except Exception as e:
            return f"❌ Error blocking device: {e}"

    # ═══════════════════════════════════════════════════════════════════════
    # MESSAGE PROCESSING
    # ═══════════════════════════════════════════════════════════════════════

    def process_message(self, chat_id: int, text: str) -> str:
        self.activity.emit(ActivityStream.QUERY_RECEIVED, f"TG msg: {text[:80]}", {"chat_id": chat_id})
        conv = self.get_conversation(chat_id)
        conv.add_message("user", text)

        # === PRODUCTION: Auto chunk + summarize for extremely long inputs (>50k tokens) ===
        approx_tokens = len(text) // 4
        if approx_tokens > 50000:
            logger.info(f"[Production] Very long input detected ({approx_tokens} tokens). Applying intelligent chunk+summary...")
            try:
                # This runs synchronously here for simplicity; in real prod make it async
                text = self._chunk_and_summarize_long_prompt_sync(text)
                logger.info(f"[Production] Reduced long prompt to ~{len(text)//4} tokens")
            except Exception as e:
                logger.warning(f"Chunk+summary failed, using original (risk of OOM): {e}")

        # Also track in context manager if available
        session_id = f"telegram_{chat_id}"
        if self.context_manager:
            try:
                self.context_manager.add_message("user", text, session_id)
            except Exception as e:
                logger.debug(f"Context manager add failed: {e}")

        model = conv.current_model
        if not model:
            if self.default_model and self.default_model in self.router.available_models:
                model = self.default_model
                logger.info(f"Using telegram default model: {model}")
            else:
                model, task, _ = self.router.route_query(text)
                logger.info(f"Routed to {model} for {task.value}")
        self.activity.emit(ActivityStream.MODEL_SELECTED, f"Model: {model}", {"model": model})

        # Build prompt with context - use context manager if available
        system = "You are Larry, a helpful AI assistant. Be concise and helpful."
        
        if self.context_manager:
            try:
                context = self.context_manager.get_context_for_prompt(session_id)
                if context:
                    prompt = f"{system}\n\n{context}\n\nUser: {text}\n\nAssistant:"
                else:
                    prompt = f"{system}\n\nUser: {text}\n\nAssistant:"
            except Exception as e:
                logger.warning(f"Context manager failed: {e}")
                # Fallback to basic context
                prompt = self._build_basic_prompt(system, conv, text)
        else:
            prompt = self._build_basic_prompt(system, conv, text)

        try:
            self.activity.emit(ActivityStream.GENERATING, f"Generating via {model}...", {"prompt_len": len(prompt)})

            # Use EnhancedAgent with profiles if available
            response = None
            sources = []
            if self.agent and hasattr(self.agent, 'process_query_multi'):
                try:
                    hw_options = HW_PROFILES.get(conv.current_profile, HW_PROFILES.get("SPEED", {}))
                    if self.profile_manager:
                        try:
                            profile = self.profile_manager.get_current_profile()
                            hw_options = profile.to_ollama_options() if hasattr(profile, 'to_ollama_options') else hw_options
                        except Exception:
                            pass
                    response, sources = self.agent.process_query_multi(
                        text, history=conv.messages[:-1],
                        profile_name=conv.current_profile,
                        skill_name=conv.current_skill,
                        hw_options=hw_options
                    )
                except Exception as e:
                    logger.warning(f"EnhancedAgent failed, falling back to router: {e}")

            # Fallback to direct router
            if response is None:
                response = self.router.generate(prompt, model=model)

            self.activity.emit(ActivityStream.RESPONSE_DONE, f"Response: {len(response)} chars", {"model": model, "response_len": len(response)})
            conv.add_message("assistant", response)

            # Debug mode: append RAG sources
            if conv.debug_mode and sources:
                response += "\n\n📎 Sources: " + ", ".join(str(s)[:50] for s in sources[:5])

            # Store conversation in RAG memory
            if self.rag_manager:
                try:
                    self.rag_manager.store_conversation(text, response, {"chat_id": str(chat_id)})
                except Exception as e:
                    logger.debug(f"RAG storage failed: {e}")

            # Track response in context manager
            if self.context_manager:
                try:
                    self.context_manager.add_message("assistant", response, session_id)
                except Exception as e:
                    logger.warning(f"Context manager add_message failed: {e}")

            return response
        except Exception as e:
            self.activity.emit(ActivityStream.ERROR, f"Generation failed: {e}")
            logger.error(f"Generation failed: {e}")
            return f"❌ Error: {e}"
    
    def _get_basic_context(self, conv: ConversationContext) -> str:
        """Get basic conversation context string."""
        if len(conv.messages) > 1:
            return "\n".join([
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in conv.messages[-6:-1]
            ])
        return ""
    
    def _build_basic_prompt(self, system: str, conv: ConversationContext, text: str) -> str:
        """Build prompt with basic conversation context."""
        if len(conv.messages) > 1:
            context = "\n".join([
                f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                for m in conv.messages[-6:-1]
            ])
            return f"{system}\n\nRecent conversation:\n{context}\n\nUser: {text}\n\nAssistant:"
        else:
            return f"{system}\n\nUser: {text}\n\nAssistant:"

    def handle_update(self, update: dict):
        message = update.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        voice = message.get("voice")

        if not chat_id:
            return

        if not self.is_allowed(chat_id):
            self.send_message(chat_id, "⛔ Access denied.")
            return

        # Rate limiting
        if self._rate_limited(chat_id):
            self.send_message(chat_id, "⏳ Rate limited. Please wait a moment.")
            return

        # ===================== LONG PROMPT / DOCUMENT SUPPORT (Production Feature) =====================
        # Allow users to send several thousand lines as multiple messages or files.
        # Everything is concatenated into ONE clean prompt string later.
        sess = self.session_mgr.get_session(chat_id)

        # Document upload support (for very long prompts / training data)
        document = message.get("document")
        if document:
            if sess["prompt_building"]:
                file_path = self.download_file(document["file_id"])
                if file_path:
                    try:
                        content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
                        self.session_mgr.add_prompt_part(chat_id, content)
                        self.send_message(chat_id, f"📄 Document added to prompt buffer ({len(content)} chars). Send more or /submit.")
                    except Exception as e:
                        self.send_message(chat_id, f"❌ Failed to read document: {e}")
                    finally:
                        try:
                            Path(file_path).unlink(missing_ok=True)
                        except Exception:
                            pass
            else:
                self.send_message(chat_id, "📄 Document received. Start with /longprompt first if you want to use it as a big prompt.")
            return

        # If user is in long-prompt building mode, accumulate instead of normal processing
        if sess["prompt_building"]:
            if text.startswith("/"):
                # Allow commands even in building mode
                pass  # fall through to command handling below
            else:
                self.session_mgr.add_prompt_part(chat_id, text)
                self.send_message(chat_id, f"📝 Added to long prompt buffer ({len(sess['prompt_buffer'])} parts so far). Use /submit when done.")
                return

        # ===================== END LONG PROMPT SUPPORT =====================

        # Handle voice messages
        if voice and self.voice_manager:
            self.handle_voice_message(chat_id, voice)
            return

        # Handle text messages
        if not text:
            return

        # Normal input length check (bypassed during long prompt mode)
        if len(text) > self.max_input_chars:
            self.send_message(chat_id, f"⚠️ Message too long ({len(text)} chars). Max: {self.max_input_chars} (use /longprompt for bigger inputs)")
            return
        
        logger.info(f"[{chat_id}] Received: {text[:50]}...")
        
        # Handle commands
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower().split("@")[0]  # Remove @botname
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd in self.commands:
                response = self.commands[cmd](chat_id, args)
                self.send_message(chat_id, response)
                return
        
        # Process regular message
        self.send_typing(chat_id)
        response = self.process_message(chat_id, text)
        self.send_message(chat_id, response)
    
    def handle_voice_message(self, chat_id: int, voice: dict):
        """Handle incoming voice messages."""
        try:
            # Get voice file info
            file_id = voice.get("file_id")
            duration = voice.get("duration", 0)
            
            logger.info(f"[{chat_id}] Voice message received: {duration}s")
            
            # Download voice file
            file_path = self.download_file(file_id)
            if not file_path:
                self.send_message(chat_id, "❌ Failed to download voice message")
                return
            
            # Transcribe voice to text
            self.send_typing(chat_id)
            transcribed_text = self.voice_manager.transcribe(file_path)
            
            if not transcribed_text.strip():
                self.send_message(chat_id, "❌ Could not transcribe voice message")
                return
            
            logger.info(f"[{chat_id}] Transcribed: {transcribed_text[:50]}...")
            
            # Process transcribed text as regular message
            response = self.process_message(chat_id, transcribed_text)
            
            # Send text response
            self.send_message(chat_id, f"🎤 *Voice Input:* {transcribed_text}\n\n💬 *Response:* {response}")
            
            # Optionally send voice response if voice tasks enabled
            if self.voice_manager.should_respond_with_voice("chat"):
                try:
                    audio_path = self.voice_manager.speak(response)
                    self.send_voice(chat_id, audio_path, caption="🎭 Voice Response")
                except Exception as e:
                    logger.warning(f"Voice response failed: {e}")
            
        except Exception as e:
            logger.error(f"Voice message handling failed: {e}")
            self.send_message(chat_id, f"❌ Voice processing error: {e}")
    
    def download_file(self, file_id: str) -> Optional[str]:
        """Download file from Telegram."""
        try:
            # Get file path
            result = self._api_call("getFile", {"file_id": file_id})
            if not result.get("ok"):
                return None
            
            file_path = result["result"]["file_path"]
            
            # Download file — token kept out of logs
            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            try:
                response = requests.get(download_url, timeout=30)
            except Exception as e:
                logger.error("File download failed (token redacted)")
                return None
            if response.status_code != 200:
                return None
            
            # Save to temp file
            import tempfile
            import os
            
            temp_dir = tempfile.gettempdir()
            ext = os.path.splitext(file_path)[1] or ".ogg"  # Voice files are usually OGG
            temp_path = os.path.join(temp_dir, f"telegram_voice_{file_id}{ext}")
            
            with open(temp_path, "wb") as f:
                f.write(response.content)
            
            return temp_path
            
        except Exception as e:
            logger.error(f"File download failed: {e}")
            return None
    
    def send_voice(self, chat_id: int, voice_path: str, caption: str = None):
        """Send voice message."""
        try:
            with open(voice_path, "rb") as f:
                files = {"voice": f}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                result = requests.post(
                    f"{self.base_url}/sendVoice",
                    files=files,
                    data=data,
                    timeout=30
                )
                
                if not result.json().get("ok"):
                    logger.error(f"Voice send failed: {result.json()}")
                    
        except Exception as e:
            logger.error(f"Voice send error: {e}")

    def _drain_pending_updates(self):
        """Acknowledge (skip) any backlog of updates so the bot does not replay
        old messages that piled up while it was offline.

        Telegram retains un-confirmed updates for ~24h. Without this, every
        restart reprocesses the entire backlog — which looks like the bot
        'looping on old messages'. We fetch the most recent pending update,
        advance our offset past it, and confirm it without handling anything.
        """
        try:
            # offset=-1 returns only the most recent pending update (if any).
            result = self._api_call("getUpdates", {"offset": -1, "timeout": 0}, timeout=10, retries=1)
            updates = result.get("result", []) if result.get("ok") else []
            if updates:
                self.last_update_id = updates[-1]["update_id"]
                # Confirm everything up to and including last_update_id so Telegram
                # stops re-delivering the backlog on the next poll.
                self._api_call(
                    "getUpdates",
                    {"offset": self.last_update_id + 1, "timeout": 0},
                    timeout=10,
                    retries=1,
                )
                logger.info(f"Skipped backlog: confirmed updates up to id {self.last_update_id}")
            else:
                logger.info("No pending backlog to skip")
        except Exception as e:
            logger.warning(f"Failed to drain pending updates: {e}")

    def run(self):
        """Main polling loop."""
        logger.info("🤖 Telegram bot starting...")
        logger.info(f"Available models: {len(self.router.available_models)}")

        # Skip the offline backlog so we don't replay old messages on startup.
        if self.skip_pending:
            self._drain_pending_updates()

        self.running = True

        while self.running:
            try:
                updates = self.get_updates(offset=self.last_update_id + 1, timeout=30)
                for update in updates:
                    self.last_update_id = update["update_id"]
                    self.handle_update(update)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.running = False
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(5)

    def stop(self):
        self.running = False


def main():
    """Main entry point with enhanced visuals."""
    print_banner()
    
    print_section("Initialization", "⚡")
    
    try:
        # Loading animation
        spinner = Spinner("Connecting to Telegram API", "dots")
        spinner.start()
        time.sleep(0.5)
        
        bot = TelegramBot()
        spinner.stop("Connected to Telegram")
        
        # Show status
        print_status(f"Bot token configured", "ok")
        print_status(f"Models available: {Colors.CYAN}{len(bot.router.available_models)}{Colors.END}", "ok")
        
        if bot.file_browser:
            print_status(f"File browser ready", "ok")
        if bot.context_manager:
            print_status(f"Context manager active", "ok")
        if bot.mcp_toolkit:
            print_status(f"MCP toolkit loaded", "ok")
        if bot.rag_manager:
            stats = bot.rag_manager.get_stats()
            print_status(f"RAG memory: {stats.get('total_documents', 0)} documents", "ok")
        if bot.voice_manager:
            vstats = bot.voice_manager.get_status()
            voice_features = []
            if vstats.get('stt_available'):
                voice_features.append("STT")
            if vstats.get('tts_available'):
                voice_features.append("TTS")
            if vstats.get('voice_cloning'):
                voice_features.append("Batman Voice")
            if voice_features:
                print_status(f"Voice: {', '.join(voice_features)}", "ok")
        
        # Ready message
        print(f"""
{Colors.GREEN}╔═══════════════════════════════════════════════════════════════╗
║  {Colors.BOLD}🚀 BOT IS READY!{Colors.END}{Colors.GREEN}                                            ║
╠═══════════════════════════════════════════════════════════════╣
║  {Colors.WHITE}📱 Send a message to your bot on Telegram{Colors.GREEN}                 ║
║  {Colors.WHITE}⌨️  Press Ctrl+C to stop{Colors.GREEN}                                  ║
╚═══════════════════════════════════════════════════════════════╝{Colors.END}
""")
        
        # Show available commands
        print_section("Available Commands", "📋")
        commands = [
            ("/help", "Show help menu"),
            ("/models", "List AI models"),
            ("/status", "Bot status"),
            ("/ls", "List files"),
            ("/run", "Execute command"),
        ]
        for cmd, desc in commands:
            print(f"  {Colors.CYAN}{cmd:12}{Colors.END} {Colors.DIM}{desc}{Colors.END}")
        
        print(f"\n{Colors.DIM}  ...and more! Use /help in Telegram{Colors.END}\n")
        
        # Start polling
        print_section("Polling", "📡")
        print_status("Listening for messages...", "run")
        print()
        
        bot.run()
        
    except ValueError as e:
        print_status(f"Configuration error: {e}", "error")
        print(f"\n{Colors.YELLOW}💡 Set TELEGRAM_BOT_TOKEN in .env file{Colors.END}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}👋 Bot stopped by user{Colors.END}")
    except Exception as e:
        print_status(f"Error: {e}", "error")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
