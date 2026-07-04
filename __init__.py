"""
Larry G-Force Skills Framework

Skills are local Python modules that the agent can discover and execute.
They are designed as lightweight, Ollama-friendly MCP-style tools.

Each skill should:
- Be importable
- Expose a `run(**kwargs)` function
- Optionally define `description`, `parameters`, and `category`
"""

from pathlib import Path
import importlib
import inspect

SKILLS_DIR = Path(__file__).parent

def discover_skills():
    """Dynamically discover all skills in the skills/ directory."""
    skills = {}
    for py_file in SKILLS_DIR.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        module_name = py_file.stem
        try:
            module = importlib.import_module(f"skills.{module_name}")
            if hasattr(module, "run"):
                skills[module_name] = {
                    "module": module,
                    "description": getattr(module, "description", ""),
                    "parameters": getattr(module, "parameters", {}),
                    "category": getattr(module, "category", "general"),
                }
        except Exception as e:
            print(f"Failed to load skill {module_name}: {e}")
    return skills

def run_skill(skill_name: str, **kwargs):
    """Execute a skill by name."""
    skills = discover_skills()
    if skill_name not in skills:
        return {"error": f"Skill '{skill_name}' not found"}
    
    skill = skills[skill_name]
    try:
        result = skill["module"].run(**kwargs)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}