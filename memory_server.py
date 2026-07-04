"""Native Memory / Knowledge Graph MCP Server."""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from .base import BaseMCPServer


class MemoryServer(BaseMCPServer):
    def __init__(self, storage_path: str = "./memory.json", max_entities: int = 10000):
        self.path = Path(storage_path)
        self.max_entities = max_entities
        self._graph: Dict = {"entities": {}, "relations": [], "updated_at": None}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._graph = json.loads(self.path.read_text())
            except Exception:
                pass

    def _save(self):
        self._graph["updated_at"] = datetime.now().isoformat()
        self.path.write_text(json.dumps(self._graph, indent=2))

    def create_entities(self, entities: List[Dict]) -> dict:
        created = []
        for e in entities:
            name = e.get("name") or e.get("entity_name", "")
            if not name:
                continue
            if name not in self._graph["entities"]:
                self._graph["entities"][name] = {
                    "name": name,
                    "entity_type": e.get("entity_type", "unknown"),
                    "observations": e.get("observations", []),
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                }
                created.append(name)
        self._save()
        return {"created": created, "count": len(created)}

    def create_relations(self, relations: List[Dict]) -> dict:
        added = []
        for r in relations:
            if r not in self._graph["relations"]:
                self._graph["relations"].append(r)
                added.append(r)
        self._save()
        return {"added": added, "count": len(added)}

    def add_observations(self, observations: List[Dict]) -> dict:
        updated = []
        for o in observations:
            name = o.get("entity_name", "")
            obs = o.get("contents", o.get("observations", []))
            if isinstance(obs, str):
                obs = [obs]
            if name in self._graph["entities"]:
                self._graph["entities"][name]["observations"].extend(obs)
                self._graph["entities"][name]["updated_at"] = datetime.now().isoformat()
                updated.append(name)
        self._save()
        return {"updated": updated}

    def search_nodes(self, query: str) -> dict:
        q = query.lower()
        results = []
        for name, ent in self._graph["entities"].items():
            if q in name.lower() or any(q in ob.lower() for ob in ent.get("observations", [])):
                results.append(ent)
        return {"results": results, "count": len(results)}

    def read_graph(self) -> dict:
        return {
            "entities": list(self._graph["entities"].values()),
            "relations": self._graph["relations"],
            "entity_count": len(self._graph["entities"]),
            "relation_count": len(self._graph["relations"]),
        }

    def get_entity(self, name: str) -> dict:
        return self._graph["entities"].get(name, {"error": f"Entity not found: {name}"})
