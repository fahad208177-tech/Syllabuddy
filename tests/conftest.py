import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server_url(tmp_path_factory):
    port = _free_port()
    env = os.environ | {"SYLLABUDDY_PORT": str(port), "SYLLABUDDY_DB": str(tmp_path_factory.mktemp("db") / "p.db"),
                        "PYTHONIOENCODING": "utf-8"}
    # Log to a file, never an unread PIPE: once the pipe buffer fills, the server
    # blocks on its next log line and every later request hangs.
    log_path = tmp_path_factory.mktemp("logs") / "mcp_server.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen([sys.executable, "-m", "mcp_server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 240
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(log_path.read_text(errors="replace"))
        try:
            httpx.get(url, timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.5)
    yield url
    proc.terminate()
    proc.wait(timeout=10)
    log.close()


