#!/usr/bin/env python3
"""Toggle the GPU gaming cap in BOTH larry_config.json copies (root + src).

Usage:  set_gaming.py on|off
The cap (model_router clamps Ollama num_gpu) is re-read live on the next query,
so no agent/bot restart is needed once the new router code is loaded.
"""
import json
import os
import sys

mode = (sys.argv[1].lower() if len(sys.argv) > 1 else "on") in ("on", "true", "1", "yes")
here = os.path.dirname(os.path.abspath(__file__))
targets = [
    os.path.join(here, "larry_config.json"),
    os.path.join(here, "src", "larry_config.json"),
]

for t in targets:
    if not os.path.exists(t):
        print("skip (missing):", t)
        continue
    with open(t, "r", encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("gpu_gaming", {})["gaming_mode"] = mode
    with open(t, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=4, ensure_ascii=False)
        f.write("\n")
    print(f"{'ON ' if mode else 'OFF'}  gaming_mode={mode}  ->  {t}")

print()
if mode:
    print("GPU gaming cap ENABLED  — num_gpu capped to ~50%, ~5GB VRAM freed for games.")
else:
    print("GPU gaming cap DISABLED — full GPU offload, fastest inference.")
print("Effect applies on the next agent/bot query (no restart needed).")
