@echo off
setlocal

REM Lives in launchers\ — work from the repo root one level up.
cd /d "%~dp0\.."

REM Canonical: system Python311 (NOT the repo .venv) running the src\ tree.
set "PY=C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

echo [Larry] Bootstrapping paths...
"%PY%" -c "import sys; sys.path.insert(0, 'src'); import larry_paths; larry_paths.bootstrap()" 2>nul

echo [Larry] Launching via src\manage_larry.py ...
"%PY%" src\manage_larry.py start-agent %*

endlocal
