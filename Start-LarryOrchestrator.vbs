' ============================================================
'  Larry G-Force - MASTER ORCHESTRATOR auto-start (login), hidden
'  Single A-Z login entry: WSL2 + Ollama + dashboard + governor +
'  Telegram + (optional) API/docker/MCP, brought up resource-tiered.
'  Replaces the old "Larry G-Force System" + "WSL Kali Keepalive"
'  Startup entries (those are disabled to prevent duplicate stacks
'  and duplicate dashboard logins). Runs hidden, no console window.
' ============================================================
CreateObject("WScript.Shell").Run """C:\Users\LocalLarry\AppData\Local\Programs\Python\Python311\python.exe"" ""C:\Users\LocalLarry\Documents\LocalLarry\GITHUB\launchers\larry_orchestrator.py""", 0, False
