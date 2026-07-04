' ============================================================
'  Larry G-Force - WSL2 Kali auto-start (login), hidden
'  Boots the kali-linux WSL2 distro at login (hidden, no console
'  window) and HOLDS it open for the whole login session via a
'  foreground keepalive process, so WSL2 does not idle-shut-down
'  the distro and its tools stay reachable for the local Ollama
'  model. systemd is enabled inside Kali for service management.
'  Launched from the Startup shortcut. Sibling of Start-LarrySystem.bat.
' ============================================================
CreateObject("WScript.Shell").Run "wsl -d kali-linux -- bash -lc ""$HOME/larry-keepalive.sh""", 0, False
