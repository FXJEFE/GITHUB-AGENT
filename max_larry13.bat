@echo off
setlocal EnableExtensions
:: ============================================================================
::  max_larry13.bat — thin wrapper around the MASTER ORCHESTRATOR
::
::  Everything the old bat tried (and failed) to do is handled by
::  launchers\larry_orchestrator.py, properly:
::    - Ollama:  health-checked start, env tuning, 30s readiness wait
::    - MCP:     stdio servers wired via mcp_host\servers.json (started
::               lazily inside the agent's MCP host — NOT tcp ports)
::    - Agent:   src\agent_v2.py via best_python(), cwd=src, own console
::    - Plus:    singleton lock, Job Object teardown, supervision, logs\
::
::  Runs the orchestrator in the FOREGROUND on purpose: closing this
::  window (or Ctrl+C) = full stack teardown, no orphans.
::
::  Args pass through:  max_larry13.bat --status
::                      max_larry13.bat --minimal
::                      max_larry13.bat --selftest-tools qwen3:latest
:: ============================================================================

set "ROOT=C:\Users\LocalLarry\Documents\LocalLarry\GITHUB"

:: Locate the orchestrator (launchers\ preferred, repo root as fallback)
set "ORCH=%ROOT%\launchers\larry_orchestrator.py"
if not exist "%ORCH%" set "ORCH=%ROOT%\larry_orchestrator.py"
if not exist "%ORCH%" (
    echo [!] larry_orchestrator.py not found under "%ROOT%" — aborting.
    pause
    exit /b 1
)

:: Bootstrap interpreter: repo venv first, then py launcher, then PATH.
:: (Low stakes — the orchestrator re-selects via best_python() for all
::  children; this only needs a stdlib-capable Python to boot it.)
set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not defined PY if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 set "PY=py -3.11"
)
if not defined PY set "PY=python"

echo [+] Interpreter : %PY%
echo [+] Orchestrator: "%ORCH%"
echo [+] Bringing up Larry G-Force (close window / Ctrl+C = full teardown)...
echo.

cd /d "%ROOT%"
%PY% "%ORCH%" %*
set "RC=%ERRORLEVEL%"

echo.
echo [+] Orchestrator exited (code %RC%). Logs: "%ROOT%\logs\"
pause
endlocal & exit /b %RC%
