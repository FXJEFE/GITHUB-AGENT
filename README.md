# FXJEFE Local Security & Productivity Suite v1.0

Fully local, safe MCP server for Ollama with verified Community Tools-inspired tools.

## Quick Start

Pick the section for your OS. The folder name has **no spaces** so paths stay portable across shells.

### Windows (PowerShell — recommended)

```powershell
# 1. Create project folder under your user profile
New-Item -ItemType Directory -Force "$env:USERPROFILE\FXJEFE-Local-mcp" | Out-Null
Set-Location "$env:USERPROFILE\FXJEFE-Local-mcp"

# 2. Save the three files (server, requirements, README) into this folder

# 3. Create + activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 5. Run the server
python fxjefe_local_mcp_server.py
```

> If `Activate.ps1` is blocked, run once per user:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Windows (cmd.exe)

```cmd
mkdir "%USERPROFILE%\FXJEFE-Local-mcp"
cd /d "%USERPROFILE%\FXJEFE-Local-mcp"
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
playwright install chromium
python fxjefe_local_mcp_server.py
```

### macOS / Linux (bash / zsh)

```bash
mkdir -p ~/FXJEFE-Local-mcp && cd ~/FXJEFE-Local-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python fxjefe_local_mcp_server.py
```

### In-tree (running from this repo on any OS)

If you cloned the Larry G-Force repo and just want to run the server from where it already lives:

```powershell
# From the GITHUB/ root:
python mcp\fxjefe-local-mcp\fxjefe_local_mcp_server.py
```

```bash
# From the GITHUB/ root:
python mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py
```

## Connect to an Ollama MCP Client

Use any MCP client for Ollama (e.g. `jonigl/mcp-client-for-ollama` or your own script).

Example client connection (stdio):

```python
from mcp import ClientSession, StdioServerParameters
# ... connect to the server above
```

The Larry agent's own `config/mcp.json` already declares this server with a portable relative path:

```json
{
  "name": "fxjefe-local",
  "transport": "stdio",
  "command": "python",
  "args": ["mcp/fxjefe-local-mcp/fxjefe_local_mcp_server.py"]
}
```

That command resolves correctly on Windows, macOS, and Linux as long as it is launched from the `GITHUB/` project root.

## Available Tools (10 total)

**Security**
- `static_security_scan`
- `detect_prompt_injection`

**PDF Tools**
- `extract_pdf_text`
- `merge_pdfs`
- `get_pdf_metadata`

**Browser Automation**
- `browser_navigate_and_extract`
- `browser_take_screenshot`

**File System & Search**
- `safe_list_directory`
- `safe_search_files`
- `safe_read_file`

## Safe Path Configuration

All file/PDF/browser-screenshot tools are restricted to the directories listed in `ALLOWED_ROOTS` at the top of `fxjefe_local_mcp_server.py`. Edit that constant to widen or narrow access. Recommended defaults per OS:

```python
# Windows
ALLOWED_ROOTS = [
    Path(os.environ["USERPROFILE"]) / "Documents",
    Path(os.environ["USERPROFILE"]) / "Downloads",
    Path(os.environ.get("TEMP", r"C:\Windows\Temp")),
]

# macOS / Linux
ALLOWED_ROOTS = [
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path("/tmp"),
]
```

The server uses `pathlib.Path` and `Path.home()` throughout, so it works correctly on both Windows (`C:\Users\<you>`) and POSIX (`/home/<you>` or `/Users/<you>`).

## Safety Notes

- All paths are restricted to safe directories (edit `ALLOWED_ROOTS` in code).
- No untrusted code is ever executed.
- Browser runs headless with strict timeouts.
- All logic is original and auditable.

This server gives you the **best parts** of Community Tools skills in a clean, local, malware-free package.
