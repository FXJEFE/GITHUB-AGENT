#!/usr/bin/env python3
"""
launch_with_dashboard.py
Starts the Unified Command Center on port 3777 (the official test dashboard port),
then launches agent_v2.py (or test_security_tools.py).

Usage:
    python launch_with_dashboard.py              # dashboard (3777) + agent_v2
    python launch_with_dashboard.py --test       # dashboard (3777) + test_security_tools
    python launch_with_dashboard.py --dashboard-only
"""

import subprocess
import sys
import time
import os
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def start_dashboard():
    print("🚀 Starting Unified Command Center on http://127.0.0.1:3777 ...")
    return subprocess.Popen(
        [sys.executable, str(ROOT / "UNIFIED_COMMAND_CENTER.py")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

def main():
    use_test = "--test" in sys.argv
    dashboard_only = "--dashboard-only" in sys.argv

    dash_proc = start_dashboard()
    time.sleep(2.5)  # give Flask a moment

    print("\n✅ Dashboard should be live at: http://127.0.0.1:3777")
    print("   (If you still get 500, the new templates/command_center.html is now present)")

    if dashboard_only:
        print("\nDashboard-only mode. Press Ctrl+C to stop.")
        try:
            dash_proc.wait()
        except KeyboardInterrupt:
            dash_proc.terminate()
        return

    # Launch the main thing the user asked for
    # test_security_tools.py lives in the repo root; agent_v2.py is canonical in src/
    target = ROOT / "test_security_tools.py" if use_test else ROOT / "src" / "agent_v2.py"
    print(f"\n▶ Launching {target.name} ...\n")

    try:
        subprocess.run([sys.executable, str(target)], cwd=str(target.parent))
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        if dash_proc.poll() is None:
            dash_proc.terminate()

if __name__ == "__main__":
    main()