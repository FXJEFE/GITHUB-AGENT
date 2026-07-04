"""Base classes for native MCP servers."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class MCPResponse:
    success: bool
    result: Any = None
    error: Optional[str] = None


class BaseMCPServer:
    """All native MCP servers inherit from this."""

    def call(self, method: str, params: Dict) -> MCPResponse:
        handler = getattr(self, method, None)
        if handler is None:
            return MCPResponse(success=False, error=f"Unknown method: {method}")
        try:
            result = handler(**params)
            return MCPResponse(success=True, result=result)
        except Exception as e:
            return MCPResponse(success=False, error=str(e))
