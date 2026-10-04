"""Web server for the simulated Alexa+ experience.

    python -m assistant             # http://127.0.0.1:8000

Serves the voice UI and streams each turn's events (tool calls, tool results,
the spoken answer) to the browser as newline-delimited JSON, so the screen can
show Alexa+ reaching for Syllabuddy in real time.
"""

from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from assistant.agent import Assistant, _result_data

WEB = Path(__file__).parent / "web"
assistant = Assistant()


def _clean_id(value: object, fallback: str) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in "-_")[:64]
    return text or fallback


async def index(_request: Request) -> FileResponse:
    return FileResponse(WEB / "index.html")


async def ask(request: Request) -> StreamingResponse | JSONResponse:
    body = await request.json()
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return JSONResponse({"error": "Say something first."}, status_code=400)
    session = _clean_id(body.get("session"), "default")
    student = _clean_id(body.get("student"), "anonymous")

    async def events():
        async for event in assistant.turn(session, student, text):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


async def reset(request: Request) -> JSONResponse:
    body = await request.json()
    assistant.reset(_clean_id(body.get("session"), "default"))
    return JSONResponse({"ok": True})


async def revision(request: Request) -> JSONResponse:
    """The sidebar's revision list, fetched through MCP like everything else."""
    student = _clean_id(request.query_params.get("student"), "anonymous")
    try:
        async with AsyncExitStack() as stack:
            client = await assistant._connect(stack, student)
            data = _result_data(await client.call_tool("my_revision_list", {}))
    except Exception as error:  # noqa: BLE001
        return JSONResponse({"error": str(error)}, status_code=502)
    return JSONResponse(data)


async def health(_request: Request) -> JSONResponse:
    try:
        async with AsyncExitStack() as stack:
            client = await assistant._connect(stack, "health-check")
            tools = [t.name for t in (await client.list_tools()).tools]
        mcp_ok = True
    except Exception:  # noqa: BLE001
        tools, mcp_ok = [], False
    return JSONResponse({"brain": assistant.brain.name, "mcp_url": assistant.mcp_url,
                         "mcp_ok": mcp_ok, "tools": tools})


@asynccontextmanager
async def lifespan(_app):
    """Open one MCP connection at startup so the first question isn't the slow one."""
    try:
        async with AsyncExitStack() as stack:
            client = await assistant._connect(stack, "warm-up")
            await client.list_tools()
    except Exception:  # noqa: BLE001 - the health check reports it properly
        pass
    yield


app = Starlette(lifespan=lifespan, routes=[
    Route("/", index),
    Route("/api/ask", ask, methods=["POST"]),
    Route("/api/reset", reset, methods=["POST"]),
    Route("/api/revision", revision),
    Route("/api/health", health),
    Mount("/static", StaticFiles(directory=WEB), name="static"),
])


def main() -> None:
    import uvicorn

    host = os.environ.get("ASSISTANT_HOST", "127.0.0.1")
    port = int(os.environ.get("ASSISTANT_PORT", "8000"))
    print(f"Simulated Alexa+ ({assistant.brain.name}): http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
