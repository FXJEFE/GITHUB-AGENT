# FXJEFE Local Larry - Master Activation Pipeline (PowerShell)
$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  FXJEFE LOCAL LARRY - FULL ACTIVATION PIPELINE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location "$PSScriptRoot\.."

python src\manage_larry.py activate-all

Write-Host ""
Write-Host "Pipeline finished. Review the status report above." -ForegroundColor Green
Write-Host "Useful commands:" -ForegroundColor Yellow
Write-Host "  python src\manage_larry.py mcp-test" -ForegroundColor White
Write-Host "  python src\manage_larry.py status" -ForegroundColor White
Read-Host "Press Enter to close this window"