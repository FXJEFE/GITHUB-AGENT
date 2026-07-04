"""
Example Local Skill - Converted to Python + Ollama MCP style

This is the new pattern: pure Python functions that the agent can call directly
or expose via a local MCP server. No external dependencies beyond what's already in the project.
"""

description = "Example skill showing the new local MCP-style pattern."
category = "example"
parameters = {
    "text": {"type": "string", "description": "Text to process"}
}

def run(text: str = "") -> dict:
    """Simple example tool that the agent can invoke."""
    if not text:
        return {"error": "No text provided"}
    
    processed = text.strip().upper()
    return {
        "original": text,
        "processed": processed,
        "length": len(processed),
        "note": "This is a local Python skill - no external API calls."
    }