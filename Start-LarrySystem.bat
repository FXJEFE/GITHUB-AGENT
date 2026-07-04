@echo off
REM ============================================================
REM  Larry G-Force - System Launcher (dashboard + full stack)
REM  Double-click to run, or used as the login auto-start target.
REM ============================================================
setlocal
REM %~dp0 is the launchers\ folder; its parent is the project root.
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" "launchers\start_system.py" %*
endlocal
