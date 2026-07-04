# Tiny Larry Agent Launcher (PowerShell)
# Canonical: system Python311 (NOT the repo .venv) running the src\ tree.
# Lives in launchers\ — works from the repo root one level up.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition))

# 1. Canonical interpreter
$python = "C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# 2. Canonical bootstrap (larry_paths lives in src\)
& $python -c "import sys; sys.path.insert(0, 'src'); import larry_paths; larry_paths.bootstrap()" 2>$null

# 3. Launch via central manager
& $python "src\manage_larry.py" "start-agent" @args
