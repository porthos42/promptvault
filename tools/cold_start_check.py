"""One-off cold-start measurement: venv python starts the server, health endpoint answers.

Run from backend/: uv run --no-sync python ../tools/cold_start_check.py
Prints `cold_start_seconds: <n>` on success.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

os.environ["PV_DATA_DIR"] = tempfile.mkdtemp(prefix="pv-cold-")
os.environ["PV_SEED_ON_START"] = "false"
t0 = time.perf_counter()
# The package has no __main__; start the venv's console script directly
# (this is also the real production start path, no uv resolver overhead).
script = Path(sys.executable).parent / ("promptvault.exe" if os.name == "nt" else "promptvault")
proc = subprocess.Popen(
    [str(script), "serve", "--host", "localhost", "--port", "8921"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    while time.perf_counter() - t0 < 30:
        try:
            urllib.request.urlopen("http://localhost:8921/api/v1/health", timeout=1)
            print(f"cold_start_seconds: {time.perf_counter() - t0:.2f}")
            break
        except OSError:
            time.sleep(0.05)
    else:
        print("cold_start check: never came up")
finally:
    proc.terminate()
    proc.wait(timeout=10)
