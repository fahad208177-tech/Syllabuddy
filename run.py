"""Start everything: the MCP server and the simulated Alexa+ app.

    python run.py

Then open http://127.0.0.1:8000. Ctrl+C stops both.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def wait_for(url: str, seconds: int = 300) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception as error:  # noqa: BLE001
            if getattr(error, "code", None):  # any HTTP response means it's up
                return True
            time.sleep(0.5)
    return False


def main() -> int:
    env = os.environ | {"PYTHONIOENCODING": "utf-8"}
    mcp_port = env.get("SYLLABUDDY_PORT", "8765")
    app_port = env.get("ASSISTANT_PORT", "8000")
    procs = [subprocess.Popen([sys.executable, "-m", "mcp_server"], cwd=ROOT, env=env)]
    try:
        if not wait_for(f"http://127.0.0.1:{mcp_port}/mcp"):
            print("MCP server did not start.")
            return 1
        procs.append(subprocess.Popen([sys.executable, "-m", "assistant"], cwd=ROOT, env=env))
        if wait_for(f"http://127.0.0.1:{app_port}/api/health", 60) and "--no-browser" not in sys.argv:
            webbrowser.open(f"http://127.0.0.1:{app_port}")
        print(f"\nReady: http://127.0.0.1:{app_port}   (Ctrl+C to stop)\n")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
