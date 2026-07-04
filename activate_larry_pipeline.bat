@echo off
title FXJEFE Local Larry - Master Activation Pipeline
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   FXJEFE LOCAL LARRY - FULL ACTIVATION PIPELINE
echo ============================================================
echo.

python src\manage_larry.py activate-all

echo.
echo Pipeline finished. Check the output above for status.
pause