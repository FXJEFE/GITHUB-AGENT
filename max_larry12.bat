```bat
@echo off
:: max_larry.bat
:: Startup script for agent_v2 with MCP, Ollama, and full server stack

echo [+] Starting agent_v2 with MCP, Ollama, and full server stack...

:: 1. Start Ollama Server
echo [+] Starting Ollama server...
start "" "ollama" serve

:: 2. Start MCP Servers
echo [+] Starting MCP servers...
start "" "mcp" server --port 3000
start "" "mcp" server --port 3001
start "" "mcp" server --port 3002

:: 3. Launch agent_v2
echo [+] Launching agent_v2...
start "" "python" "C:\Users\LocalLarry\Documents\LocalLarry\GITHUB\agent_v2.py"

:: 4. Optional: Log startup
echo [+] Startup complete. Check logs in C:\Users\LocalLarry\Documents\LocalLarry\GITHUB\agent_v2.log

pause
```