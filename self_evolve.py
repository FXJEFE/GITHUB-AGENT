"""
skills/self_evolve.py — Larry's self-* skill.

One Ollama-callable tool that lets the agent grow and repair itself, plus manage
its own tasks and long-term memory. The local model calls it with an `action`:

  Self-created skills:
    create_skill   - generate a brand-new skill file in skills/ from a spec
    list_skills    - list discoverable skills (file skills + learned skills.db)

  Self-healing / file management:
    heal_skill     - a skill raised an error -> ask the model to fix it, validate
                     the fix in isolation, and write it as a NEW version
    copy_skill     - duplicate a skill to a new versioned name

  Tasks (memory/tasks.db via TaskManager):
    add_task | list_tasks | complete_task | fail_task | next_task

  Memory (memory/chroma_db + skills.db via MemoryManager):
    remember | recall

File-management policy (non-destructive): working files in skills/ are NEVER
overwritten or deleted. Healing and copying always create a new version
(`name_v2.py`, `name_v3.py`, ...) and leave the original intact, so a known-good
skill is always preserved. Validation scratch files are written to the OS temp
dir, never into skills/.

Safety: every generated or healed source is validated BEFORE it is written into
skills/ — it must parse (ast) and import cleanly in a separate subprocess that
confirms a callable run() exists. A bad generation therefore can never break
skill discovery. Generation runs in a short retry loop that feeds validation
errors back to the model (the skill self-heals its own output).
"""

import ast
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent
SRC_DIR = SKILLS_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ----------------------------------------------------------------------------
# Skill metadata (discovered by skills/__init__.py)
# ----------------------------------------------------------------------------
description = (
    "Self-evolution tool: author new skills, heal broken skills, and manage the "
    "agent's own tasks and memory. Dispatches on the `action` argument."
)
category = "meta"
parameters = {
    "action": {
        "type": "string",
        "description": (
            "One of: create_skill, heal_skill, copy_skill, list_skills, add_task, "
            "list_tasks, complete_task, fail_task, next_task, remember, recall"
        ),
    },
    "name": {"type": "string", "description": "Skill name (create_skill/heal_skill/copy_skill)"},
    "new_name": {"type": "string", "description": "Destination skill name (copy_skill)"},
    "spec": {"type": "string", "description": "What the new skill should do (create_skill)"},
    "error": {"type": "string", "description": "The error/traceback to fix (heal_skill)"},
    "title": {"type": "string", "description": "Task title (add_task)"},
    "task_id": {"type": "integer", "description": "Task id (complete_task/fail_task)"},
    "text": {"type": "string", "description": "Text to remember (remember)"},
    "query": {"type": "string", "description": "Query for recall/recall tasks"},
    "model": {"type": "string", "description": "Override the model used for generation"},
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


# ----------------------------------------------------------------------------
# Lazy singletons (avoid DB/Ollama work at import/discovery time)
# ----------------------------------------------------------------------------
def _memory():
    from utils.memory_manager import MemoryManager
    return MemoryManager()


def _tasks():
    from utils.task_manager import TaskManager
    return TaskManager()


def _code_model(override=None):
    if override:
        return override
    try:
        from config import resolve_model
        return resolve_model("main")  # the coder model (LocalLarry-15b)
    except Exception:
        return "llama3.1:8b"


def _llm(prompt: str, system: str = "", model: str = None) -> str:
    """Single-shot chat completion against local Ollama."""
    import ollama
    from config import OLLAMA_HOST
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = ollama.Client(host=OLLAMA_HOST).chat(model=model, messages=messages)
    return resp["message"]["content"]


# ----------------------------------------------------------------------------
# Code extraction + isolated validation
# ----------------------------------------------------------------------------
def _extract_code(text: str) -> str:
    """Pull a python source block out of a model response."""
    fence = re.search(r"```(?:python|py)?\s*(.*?)```", text, re.DOTALL)
    code = fence.group(1) if fence else text
    return code.strip() + "\n"


def _validate_source(source: str) -> tuple[bool, str]:
    """Parse + import the source in a SEPARATE process and confirm run() exists.

    Runs isolated so any import-time side effects or crashes can't affect this
    process or the skills directory. Returns (ok, message).
    """
    try:
        ast.parse(source)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    # Scratch dir in the OS temp area (never inside skills/), cleaned up after.
    scratch = Path(tempfile.mkdtemp(prefix="larry_skillcheck_"))
    tmp = scratch / "cand.py"
    tmp.write_text(source, encoding="utf-8")
    probe = (
        "import importlib.util,sys;"
        "s=importlib.util.spec_from_file_location('cand',r'%s');"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "assert hasattr(m,'run') and callable(m.run),'missing callable run()';"
        "print('OK')" % str(tmp)
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=30, cwd=str(SRC_DIR),
        )
        if r.returncode == 0 and "OK" in r.stdout:
            return True, "valid"
        return False, (r.stderr or r.stdout).strip()[-800:]
    except subprocess.TimeoutExpired:
        return False, "validation timed out (import hangs)"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _next_version_path(name: str) -> tuple[str, int, Path]:
    """Return (base, next_version_number, path) for the next unused version file.

    `foo` and `foo_v1.py` are treated as v1; the next file is `foo_v2.py`, then
    `foo_v3.py`, etc. Never returns a path that already exists.
    """
    base = re.sub(r"_v\d+$", "", name)
    versions = []
    if (SKILLS_DIR / f"{base}.py").exists():
        versions.append(1)
    for p in SKILLS_DIR.glob(f"{base}_v*.py"):
        m = re.fullmatch(rf"{re.escape(base)}_v(\d+)", p.stem)
        if m:
            versions.append(int(m.group(1)))
    nxt = (max(versions) + 1) if versions else 1
    fname = f"{base}.py" if nxt == 1 else f"{base}_v{nxt}.py"
    return base, nxt, SKILLS_DIR / fname


_SKILL_SYSTEM = (
    "You write a single self-contained Python skill module for the Larry agent. "
    "Rules: define module-level `description` (str), `category` (str), "
    "`parameters` (dict), and a `run(**kwargs)` function that returns a JSON-"
    "serializable dict. No top-level side effects, no input(), no network unless "
    "asked. Output ONLY the python code in one ```python fence."
)


def _generate_valid(prompt: str, model: str, attempts: int = 3) -> tuple[bool, str, str]:
    """Ask the model for code, validate, and retry feeding back errors.

    Returns (ok, source, last_error). The retry loop is the skill healing its
    own generations.
    """
    err = ""
    for i in range(attempts):
        ask = prompt if i == 0 else (
            f"{prompt}\n\nYour previous attempt failed validation with:\n{err}\n"
            "Return the COMPLETE corrected module."
        )
        source = _extract_code(_llm(ask, system=_SKILL_SYSTEM, model=model))
        ok, msg = _validate_source(source)
        if ok:
            return True, source, ""
        err = msg
    return False, source, err


# ----------------------------------------------------------------------------
# Actions: self-created skills
# ----------------------------------------------------------------------------
def create_skill(name: str = "", spec: str = "", model: str = None, **_) -> dict:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        return {"error": "name must be lowercase snake_case (a-z0-9_), 2-41 chars"}
    if name.startswith("_"):
        return {"error": "skill name cannot start with '_'"}
    if not spec:
        return {"error": "spec (what the skill should do) is required"}
    target = SKILLS_DIR / f"{name}.py"
    if target.exists():
        return {"error": f"skill '{name}' already exists; use heal_skill to change it"}

    model = _code_model(model)
    prompt = (
        f"Create a skill named '{name}'.\n"
        f"It must do: {spec}\n"
        f"The run(**kwargs) function should accept the inputs implied by the spec "
        f"and return a dict describing the result."
    )
    ok, source, err = _generate_valid(prompt, model)
    if not ok:
        return {"error": "generation failed validation after retries", "detail": err}

    target.write_text(source, encoding="utf-8")
    # Persist to skills.db and remember the event.
    try:
        _memory().save_skill(name, source, description=f"self-authored: {spec[:160]}")
    except Exception:
        pass
    _remember_safe(f"Created skill '{name}': {spec}", {"kind": "create_skill", "name": name})
    return {"success": True, "skill": name, "path": str(target),
            "model": model, "bytes": len(source)}


def list_skills(**_) -> dict:
    from skills import discover_skills
    file_skills = {n: s["description"] for n, s in discover_skills().items()}
    try:
        learned = _memory().list_skills()
    except Exception:
        learned = []
    return {"file_skills": file_skills, "learned_skills": learned,
            "count": len(file_skills)}


# ----------------------------------------------------------------------------
# Actions: self-healing
# ----------------------------------------------------------------------------
def heal_skill(name: str = "", error: str = "", model: str = None, **_) -> dict:
    name = (name or "").strip().lower()
    target = SKILLS_DIR / f"{name}.py"
    if not target.exists():
        return {"error": f"skill '{name}' not found at {target}"}
    if not error:
        return {"error": "error/traceback to fix is required"}

    original = target.read_text(encoding="utf-8")
    model = _code_model(model)
    prompt = (
        f"This skill module raised an error. Fix the bug and return the COMPLETE "
        f"corrected module (same description/category/parameters/run contract).\n\n"
        f"--- ERROR ---\n{error}\n\n--- CURRENT SOURCE ({target.name}) ---\n{original}"
    )
    ok, source, err = _generate_valid(prompt, model)
    if not ok:
        return {"error": "healed version failed validation", "detail": err}

    # Non-destructive: keep the working original, write the fix as a new version.
    base, ver, new_path = _next_version_path(name)
    new_name = new_path.stem
    new_path.write_text(source, encoding="utf-8")
    try:
        importlib.invalidate_caches()
        importlib.import_module(f"skills.{new_name}")  # load the new version
    except Exception as e:
        return {"error": f"new version import failed (original untouched): {e}",
                "version_file": new_path.name}

    try:
        _memory().save_skill(new_name, source, description=f"self-healed: {error[:160]}")
    except Exception:
        pass
    _remember_safe(f"Healed skill '{name}' -> {new_path.name} for error: {error[:200]}",
                   {"kind": "heal_skill", "name": name, "version": new_path.name})
    return {"success": True, "original": f"{name}.py (preserved)",
            "new_version": new_path.name, "skill": new_name, "model": model}


def copy_skill(name: str = "", new_name: str = "", **_) -> dict:
    """Duplicate a skill. Without new_name, copies to the next version file."""
    name = (name or "").strip().lower()
    src = SKILLS_DIR / f"{name}.py"
    if not src.exists():
        return {"error": f"skill '{name}' not found"}
    if new_name:
        new_name = new_name.strip().lower()
        if not _NAME_RE.match(new_name):
            return {"error": "new_name must be lowercase snake_case (a-z0-9_)"}
        dst = SKILLS_DIR / f"{new_name}.py"
        if dst.exists():
            return {"error": f"'{new_name}' already exists; choose another name"}
    else:
        _, _, dst = _next_version_path(name)
    shutil.copy2(src, dst)
    return {"success": True, "from": src.name, "to": dst.name}


# ----------------------------------------------------------------------------
# Actions: tasks
# ----------------------------------------------------------------------------
def add_task(title: str = "", description: str = "", priority: int = 5,
             assigned_to: str = None, **_) -> dict:
    if not title:
        return {"error": "title is required"}
    tid = _tasks().add(title, description=description, priority=int(priority),
                       assigned_to=assigned_to)
    return {"success": True, "task_id": tid, "title": title}


def list_tasks(status: str = None, **_) -> dict:
    return {"tasks": _tasks().list(status=status)}


def next_task(assigned_to: str = None, **_) -> dict:
    return {"task": _tasks().next_pending(assigned_to=assigned_to)}


def complete_task(task_id: int = None, result: str = "", **_) -> dict:
    if task_id is None:
        return {"error": "task_id is required"}
    _tasks().complete(int(task_id), result=result or None)
    return {"success": True, "task_id": int(task_id), "status": "completed"}


def fail_task(task_id: int = None, result: str = "", **_) -> dict:
    if task_id is None:
        return {"error": "task_id is required"}
    _tasks().fail(int(task_id), result=result or None)
    return {"success": True, "task_id": int(task_id), "status": "failed"}


# ----------------------------------------------------------------------------
# Actions: memory
# ----------------------------------------------------------------------------
def _remember_safe(text: str, metadata: dict = None):
    try:
        _memory().remember(text, metadata=metadata)
    except Exception:
        pass  # degrade silently if embeddings/chroma unavailable


def remember(text: str = "", metadata: dict = None, **_) -> dict:
    if not text:
        return {"error": "text is required"}
    try:
        doc_id = _memory().remember(text, metadata=metadata or {"ts": time.time()})
        return {"success": True, "id": doc_id}
    except Exception as e:
        return {"error": f"remember failed: {e}"}


def recall(query: str = "", n: int = 5, **_) -> dict:
    if not query:
        return {"error": "query is required"}
    try:
        return {"results": _memory().recall(query, n=int(n))}
    except Exception as e:
        return {"error": f"recall failed: {e}"}


# ----------------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------------
_ACTIONS = {
    "create_skill": create_skill,
    "heal_skill": heal_skill,
    "copy_skill": copy_skill,
    "list_skills": list_skills,
    "add_task": add_task,
    "list_tasks": list_tasks,
    "next_task": next_task,
    "complete_task": complete_task,
    "fail_task": fail_task,
    "remember": remember,
    "recall": recall,
}


def run(action: str = "", **kwargs) -> dict:
    """Entry point. Dispatch on `action`; unknown actions list the valid ones."""
    fn = _ACTIONS.get((action or "").strip())
    if fn is None:
        return {"error": f"unknown action '{action}'",
                "valid_actions": sorted(_ACTIONS)}
    try:
        return fn(**kwargs)
    except TypeError as e:
        return {"error": f"bad arguments for {action}: {e}"}
    except Exception as e:
        return {"error": f"{action} failed: {e}"}


if __name__ == "__main__":
    print(json.dumps(run(json.loads(sys.argv[1])["action"], **json.loads(sys.argv[1]))
                     if len(sys.argv) > 1 else run("list_skills"), indent=2, default=str))
