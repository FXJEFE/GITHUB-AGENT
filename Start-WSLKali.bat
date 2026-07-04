@echo off
REM ============================================================
REM  Larry G-Force - WSL2 Kali auto-start (login)
REM  Boots the kali-linux WSL2 distro and keeps it alive in the
REM  background so its tools stay reachable for the local Ollama
REM  model. Sibling of Start-LarrySystem.bat. Window auto-closes.
REM ============================================================
wsl -d kali-linux -- bash -lc "$HOME/larry-keepalive.sh"
