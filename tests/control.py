#!/usr/bin/env python3
"""Send hyprctl arguments to an explicitly selected disposable test session."""
import json
import os
from pathlib import Path
import subprocess
import sys

def environment(connection):
    data = json.loads(Path(connection).read_text())
    runtime = Path(data["XDG_RUNTIME_DIR"]).resolve()
    if not runtime.is_relative_to(Path("/tmp")) or data["HYPRLAND_INSTANCE_SIGNATURE"] == os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        raise RuntimeError("Tests must target a disposable session under /tmp, never the live desktop")
    return os.environ | data

if __name__ == "__main__":
    env = environment(sys.argv[1])
    raise SystemExit(subprocess.run(["hyprctl", *sys.argv[2:]], env=env).returncode)
