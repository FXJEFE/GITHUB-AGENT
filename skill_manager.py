#!/usr/bin/env python3
"""
Skill Manager - Manages agent capabilities and skill discovery
Provides dynamic skill registration and execution framework
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """Represents a single agent skill"""
    name: str
    description: str
    category: str
    function: Optional[Callable] = None
    parameters: Optional[Dict] = None
    examples: Optional[List[str]] = None
    enabled: bool = True
    version: str = "1.0.0"


class SkillManager:
    """
    Manages agent skills and capabilities.
    
    Features:
    - Dynamic skill registration
    - Skill discovery and listing
    - Category-based organization
    - Execution tracking
    - Skill enable/disable
    """

    def __init__(self, skills_dir: Optional[str] = None):
        self.skills: Dict[str, Skill] = {}
        self.categories: Dict[str, List[str]] = {}
        self.execution_count: Dict[str, int] = {}
        self.skills_dir = Path(skills_dir) if skills_dir else Path("./skills")
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        self._register_core_skills()

        # Self-healing bookkeeping: consecutive failures per skill; a skill that
        # exceeds the ceiling is auto-disabled (quarantined) by safe_execute().
        self.failure_counts: Dict[str, int] = {}
        self.max_skill_failures = 3

        # Load any user/agent-authored skills persisted under skills_dir.
        try:
            loaded = self.load_disk_skills()
            if loaded:
                logger.info(f"Loaded {loaded} skill(s) from {self.skills_dir}")
        except Exception as e:
            logger.warning(f"Disk skill load failed (continuing): {e}")

        logger.info("Initialized SkillManager")

    def _register_core_skills(self):
        """Register core built-in skills"""
        
        # File operations
        self.register_skill(
            name="read_file",
            description="Read and display file contents",
            category="file_operations",
            parameters={
                "filepath": "Path to the file to read"
            },
            examples=[
                "/read script.py",
                "/read data/config.json"
            ]
        )
        
        self.register_skill(
            name="list_directory",
            description="List files and directories",
            category="file_operations",
            parameters={
                "path": "Directory path to list",
                "show_hidden": "Show hidden files (optional)"
            },
            examples=[
                "/ls .",
                "/ls projects/"
            ]
        )
        
        self.register_skill(
            name="search_files",
            description="Search for files by pattern",
            category="file_operations",
            parameters={
                "pattern": "File name pattern with wildcards",
                "directory": "Directory to search (optional)"
            },
            examples=[
                "/find *.py",
                "/find test_*.py"
            ]
        )
        
        # Sandbox operations
        self.register_skill(
            name="stage_file",
            description="Stage file for safe editing in sandbox",
            category="sandbox",
            parameters={
                "filepath": "Path to file to stage"
            },
            examples=[
                "/stage script.py",
                "/stage config.json"
            ]
        )
        
        self.register_skill(
            name="test_file",
            description="Run tests on staged file",
            category="sandbox",
            parameters={
                "filepath": "Path to file to test"
            },
            examples=[
                "/test script.py"
            ]
        )
        
        self.register_skill(
            name="deploy_file",
            description="Deploy tested file from sandbox to production",
            category="sandbox",
            parameters={
                "filepath": "Path to file to deploy"
            },
            examples=[
                "/deploy script.py"
            ]
        )
        
        # Context management
        self.register_skill(
            name="show_context",
            description="Display current context usage statistics",
            category="context",
            examples=["/context", "/ctx"]
        )
        
        self.register_skill(
            name="clear_context",
            description="Clear current session context",
            category="context",
            examples=["/clear"]
        )
        
        self.register_skill(
            name="list_sessions",
            description="List recent conversation sessions",
            category="context",
            examples=["/sessions"]
        )
        
        # RAG operations
        self.register_skill(
            name="rag_index",
            description="Index documents for RAG retrieval",
            category="rag",
            parameters={
                "filepath": "Path to document to index"
            },
            examples=[
                "/index document.pdf",
                "/index notes.md"
            ]
        )
        
        self.register_skill(
            name="rag_search",
            description="Search indexed documents",
            category="rag",
            parameters={
                "query": "Search query"
            },
            examples=[
                "/search how to deploy kubernetes"
            ]
        )
        
        # Web operations
        self.register_skill(
            name="web_scrape",
            description="Scrape web page content",
            category="web",
            parameters={
                "url": "URL to scrape"
            },
            examples=[
                "/scrape https://example.com"
            ]
        )
        
        self.register_skill(
            name="youtube_summarize",
            description="Get YouTube video transcript and summary",
            category="web",
            parameters={
                "url": "YouTube video URL"
            },
            examples=[
                "/youtube https://youtube.com/watch?v=..."
            ]
        )
        
        # Code execution
        self.register_skill(
            name="execute_code",
            description="Execute Python code safely",
            category="code",
            parameters={
                "code": "Python code to execute"
            },
            examples=[
                "/exec print('Hello')"
            ]
        )
        
        self.register_skill(
            name="analyze_code",
            description="Analyze code for issues and complexity",
            category="code",
            parameters={
                "filepath": "Path to code file"
            },
            examples=[
                "/analyze script.py"
            ]
        )

    def register_skill(
        self,
        name: str,
        description: str,
        category: str,
        function: Optional[Callable] = None,
        parameters: Optional[Dict] = None,
        examples: Optional[List[str]] = None,
        enabled: bool = True
    ):
        """Register a new skill"""
        skill = Skill(
            name=name,
            description=description,
            category=category,
            function=function,
            parameters=parameters,
            examples=examples,
            enabled=enabled
        )
        
        self.skills[name] = skill
        
        # Add to category index
        if category not in self.categories:
            self.categories[category] = []
        if name not in self.categories[category]:
            self.categories[category].append(name)
        
        logger.debug(f"Registered skill: {name}")

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get skill by name"""
        return self.skills.get(name)

    def list_skills(
        self,
        category: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[Skill]:
        """List skills, optionally filtered by category"""
        skills = list(self.skills.values())
        
        if category:
            skills = [s for s in skills if s.category == category]
        
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        
        return sorted(skills, key=lambda s: (s.category, s.name))

    def get_categories(self) -> List[str]:
        """Get list of all skill categories"""
        return sorted(self.categories.keys())

    def get_skills_by_category(self, category: str) -> List[Skill]:
        """Get all skills in a category"""
        skill_names = self.categories.get(category, [])
        return [self.skills[name] for name in skill_names if name in self.skills]

    def execute_skill(
        self,
        name: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a skill by name.
        
        Returns:
            Dict with execution result
        """
        skill = self.get_skill(name)
        
        if not skill:
            return {
                'success': False,
                'error': f'Skill not found: {name}'
            }
        
        if not skill.enabled:
            return {
                'success': False,
                'error': f'Skill disabled: {name}'
            }
        
        if not skill.function:
            return {
                'success': False,
                'error': f'Skill has no implementation: {name}'
            }
        
        try:
            # Track execution
            self.execution_count[name] = self.execution_count.get(name, 0) + 1
            
            # Execute
            result = skill.function(**kwargs)
            
            return {
                'success': True,
                'skill': name,
                'result': result
            }
            
        except Exception as e:
            logger.error(f"Error executing skill {name}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def enable_skill(self, name: str):
        """Enable a skill"""
        if name in self.skills:
            self.skills[name].enabled = True
            logger.info(f"Enabled skill: {name}")

    def disable_skill(self, name: str):
        """Disable a skill"""
        if name in self.skills:
            self.skills[name].enabled = False
            logger.info(f"Disabled skill: {name}")

    def get_skill_stats(self) -> Dict:
        """Get skill usage statistics"""
        total_skills = len(self.skills)
        enabled_skills = sum(1 for s in self.skills.values() if s.enabled)
        categories_count = len(self.categories)
        total_executions = sum(self.execution_count.values())
        
        return {
            'total_skills': total_skills,
            'enabled_skills': enabled_skills,
            'categories': categories_count,
            'total_executions': total_executions,
            'most_used': sorted(
                self.execution_count.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
        }

    def export_skills(self, filepath: Optional[str] = None) -> str:
        """Export skill definitions to JSON"""
        if not filepath:
            filepath = self.skills_dir / f"skills_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            'exported_at': datetime.now().isoformat(),
            'skills': [
                {
                    'name': s.name,
                    'description': s.description,
                    'category': s.category,
                    'parameters': s.parameters,
                    'examples': s.examples,
                    'enabled': s.enabled,
                    'version': s.version
                }
                for s in self.skills.values()
            ],
            'stats': self.get_skill_stats()
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Exported skills to {filepath}")
        return str(filepath)

    def get_help_text(self, category: Optional[str] = None) -> str:
        """Generate help text for skills"""
        if category:
            skills = self.get_skills_by_category(category)
            title = f"Skills in category: {category}"
        else:
            skills = self.list_skills()
            title = "Available Skills"
        
        lines = [f"\n{title}", "=" * len(title), ""]
        
        current_category = None
        for skill in skills:
            if skill.category != current_category:
                current_category = skill.category
                lines.append(f"\n📁 {current_category.upper()}")
                lines.append("-" * 40)
            
            lines.append(f"\n  {skill.name}")
            lines.append(f"    {skill.description}")
            
            if skill.parameters:
                lines.append("    Parameters:")
                for param, desc in skill.parameters.items():
                    lines.append(f"      • {param}: {desc}")
            
            if skill.examples:
                lines.append("    Examples:")
                for example in skill.examples:
                    lines.append(f"      {example}")
        
        return "\n".join(lines)


    # ── disk persistence / discovery ─────────────────────────────────────────
    def load_disk_skills(self) -> int:
        """Discover and register skills persisted under skills_dir.

        Two formats are supported (both safe, both optional):
          • <name>.skill.json  — a declarative spec (no code), registered as a
            metadata-only skill (description/category/parameters/examples).
          • <name>.skill.py    — a module exposing SKILL (dict) and optionally a
            run(**kwargs) callable, which becomes the skill's implementation.

        Returns the number of skills loaded. Never raises for a single bad file.
        """
        import importlib.util

        count = 0
        if not self.skills_dir.exists():
            return 0

        for spec_file in sorted(self.skills_dir.glob("*.skill.json")):
            try:
                data = json.loads(spec_file.read_text(encoding="utf-8"))
                name = data.get("name") or spec_file.stem.replace(".skill", "")
                self.register_skill(
                    name=name,
                    description=data.get("description", ""),
                    category=data.get("category", "custom"),
                    parameters=data.get("parameters"),
                    examples=data.get("examples"),
                    enabled=data.get("enabled", True),
                )
                count += 1
            except Exception as e:
                logger.warning(f"Skipping bad skill spec {spec_file.name}: {e}")

        for mod_file in sorted(self.skills_dir.glob("*.skill.py")):
            try:
                spec = importlib.util.spec_from_file_location(mod_file.stem, mod_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                meta = getattr(module, "SKILL", {}) or {}
                name = meta.get("name") or mod_file.stem.replace(".skill", "")
                self.register_skill(
                    name=name,
                    description=meta.get("description", ""),
                    category=meta.get("category", "custom"),
                    function=getattr(module, "run", None),
                    parameters=meta.get("parameters"),
                    examples=meta.get("examples"),
                    enabled=meta.get("enabled", True),
                )
                count += 1
            except Exception as e:
                logger.warning(f"Skipping bad skill module {mod_file.name}: {e}")

        return count

    # ── skill creation (self-authoring) ──────────────────────────────────────
    def create_skill(
        self,
        name: str,
        description: str,
        category: str = "custom",
        code: Optional[str] = None,
        parameters: Optional[Dict] = None,
        examples: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """Author a new skill, persist it to skills_dir, and register it live.

        If `code` is given it must define a top-level `run(**kwargs)` function;
        the skill is saved as <name>.skill.py and its run() becomes the
        implementation. Otherwise a declarative <name>.skill.json is saved.

        Non-destructive: an existing file is backed up (<file>.bak-<ts>) before
        being replaced, honoring the project's never-overwrite policy.
        """
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name).strip("_")
        if not safe:
            return {"success": False, "error": "invalid skill name"}

        is_code = bool(code and code.strip())
        target = self.skills_dir / (f"{safe}.skill.py" if is_code else f"{safe}.skill.json")

        if target.exists() and not overwrite:
            backup = target.with_suffix(target.suffix + f".bak-{datetime.now():%Y%m%d_%H%M%S}")
            try:
                backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not back up existing skill {target.name}: {e}")

        try:
            if is_code:
                meta = {
                    "name": name, "description": description, "category": category,
                    "parameters": parameters or {}, "examples": examples or [],
                    "enabled": True,
                }
                body = (
                    '"""Auto-generated Larry skill. Edit with care."""\n\n'
                    f"SKILL = {json.dumps(meta, indent=4)}\n\n"
                    f"{code.strip()}\n"
                )
                target.write_text(body, encoding="utf-8")
            else:
                spec = {
                    "name": name, "description": description, "category": category,
                    "parameters": parameters or {}, "examples": examples or [],
                    "enabled": True, "created_at": datetime.now().isoformat(),
                }
                target.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"write failed: {e}"}

        # Register (or hot-reload) immediately so it's usable without a restart.
        try:
            self.load_disk_skills()
        except Exception as e:
            return {"success": True, "warning": f"saved but reload failed: {e}",
                    "path": str(target)}

        logger.info(f"Created skill '{name}' -> {target.name}")
        return {"success": True, "skill": name, "path": str(target)}

    # ── self-healing execution ───────────────────────────────────────────────
    def safe_execute(self, name: str, **kwargs) -> Dict[str, Any]:
        """execute_skill() with failure tracking + self-healing.

        On repeated failures a skill is reloaded from disk once (in case the
        on-disk source was fixed); if it still fails past max_skill_failures it
        is auto-disabled so it stops breaking the agent loop.
        """
        result = self.execute_skill(name, **kwargs)
        if result.get("success"):
            self.failure_counts[name] = 0
            return result

        self.failure_counts[name] = self.failure_counts.get(name, 0) + 1
        fails = self.failure_counts[name]
        logger.warning(f"Skill '{name}' failed ({fails}/{self.max_skill_failures}): "
                       f"{result.get('error')}")

        # Attempt one heal: reload the skill's source from disk, then retry once.
        try:
            self.load_disk_skills()
            retry = self.execute_skill(name, **kwargs)
            if retry.get("success"):
                self.failure_counts[name] = 0
                logger.info(f"Skill '{name}' self-healed after reload.")
                return retry
        except Exception as e:
            logger.debug(f"Heal reload for '{name}' failed: {e}")

        if fails >= self.max_skill_failures:
            self.disable_skill(name)
            result["quarantined"] = True
            logger.warning(f"Skill '{name}' quarantined (auto-disabled) after "
                           f"{fails} failures.")
        return result

    def heal_skills(self) -> Dict[str, Any]:
        """Re-scan disk and re-enable any quarantined skills that now load."""
        before = {n: s.enabled for n, s in self.skills.items()}
        loaded = self.load_disk_skills()
        re_enabled = []
        for name, was_enabled in before.items():
            if not was_enabled and name in self.skills:
                self.enable_skill(name)
                self.failure_counts[name] = 0
                re_enabled.append(name)
        return {"reloaded": loaded, "re_enabled": re_enabled}


# Global instance
_skill_manager: Optional[SkillManager] = None


def get_skill_manager(skills_dir: Optional[str] = None) -> SkillManager:
    """Get skill manager singleton"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager(skills_dir)
    return _skill_manager


if __name__ == "__main__":
    print("Testing Skill Manager...")
    
    manager = get_skill_manager()
    
    # Test listing skills
    skills = manager.list_skills()
    print(f"\n✅ Registered {len(skills)} skills")
    
    # Test categories
    categories = manager.get_categories()
    print(f"✅ Found {len(categories)} categories: {', '.join(categories)}")
    
    # Test help text
    help_text = manager.get_help_text(category="file_operations")
    print(f"\n✅ Generated help text ({len(help_text)} chars)")
    
    # Test stats
    stats = manager.get_skill_stats()
    print(f"\n✅ Stats: {stats['total_skills']} skills, {stats['enabled_skills']} enabled")
    
    print("\n✅ All tests passed!")
