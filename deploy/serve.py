"""Everything on one port: the simulated Alexa+ web app and the public MCP server.

    SYLLABUDDY_PUBLIC_URL=https://you-syllabuddy.hf.space python -m deploy.serve

Hosts with a single exposed port (Hugging Face Spaces, Render, Fly.io, App
Runner) get one process serving:

    /                      the voice web app (and /api/*, /privacy, /terms)
    /mcp                   the MCP server, for Alexa+, Claude or any MCP client
    /authorize, /token,    OAuth 2.1 account linking (PKCE, dynamic client
    /register, /revoke,    registration), and the sign-in page a student sees
    /link, /.well-known/*

The web app's agent talks to /mcp over loopback with a first-party token, the
same way an outside client would, so the demo exercises the real protocol.
"""

from __future__ import annotations

import os
import secrets
import threading
from contextlib import asynccontextmanager

from syllabus_core.envfile import load_env

load_env()
PORT = int(os.environ.get("PORT", "7860"))
os.environ.setdefault("SYLLABUDDY_MCP_URL", f"http://127.0.0.1:{PORT}/mcp")
# A fresh first-party token per start unless one is configured; only this process knows it.
os.environ.setdefault("SYLLABUDDY_APP_TOKEN", secrets.token_urlsafe(32))
os.environ.setdefault("SYLLABUDDY_RATE_LIMIT", "8")

from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount  # noqa: E402

from assistant import app as web  # noqa: E402
from mcp_server import server  # noqa: E402

if not server.PUBLIC_URL:
    print("Note: SYLLABUDDY_PUBLIC_URL is not set, so account linking is off and /mcp is open.", flush=True)

mcp_app = server.mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")


@asynccontextmanager
async def lifespan(_app):
    # Load the syllabus and embedding model in the background so the port opens at once.
    threading.Thread(target=server.service, daemon=True).start()
    async with server.mcp.session_manager.run():
        yield


app = Starlette(lifespan=lifespan, routes=[*web.app.routes, Mount("/", app=mcp_app)])


def main() -> None:
    import uvicorn

    print(f"Syllabuddy on :{PORT}  (web app at /, MCP at /mcp, brain: {web.assistant.brain.name})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning", proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
