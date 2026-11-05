"""FastAPI app: composition root. Wires config, DB, checkpointer, MCP tools, ports and the ChatRunner.

Endpoints: WebSocket `/ws/chat/{chat_id}` (protocol v2, api/ws.py), REST `/api/v1/*` (api/rest.py),
and the built frontend.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from automind.acquisition.registry.application.seed import seed_if_empty
from automind.api import access, rest
from automind.api import admin as admin_api
from automind.api import metrics as metrics_api
from automind.api.ws import chat_socket
from automind.config import settings
from automind.infrastructure import db
from automind.infrastructure.adapters import live_ports
from automind.infrastructure.checkpoint import checkpointer
from automind.infrastructure.config import configure_domain
from automind.infrastructure.db.repositories import CaseRepo, ChatRepo, EventRepo, MessageRepo, TurnRepo
from automind.infrastructure.events import EventBus
from automind.infrastructure.llm_gateway import new_budget
from automind.infrastructure.retention import retention_loop
from automind.orchestration import graph as hub
from automind.orchestration.prompts import load_all as load_prompts
from automind.orchestration.runner import ChatRunner


async def _mcp_tools(stack: AsyncExitStack) -> list[Any]:
    """Start the MCP server (stdio) once and load its tools; analysts get scoped subsets."""
    try:
        client = MultiServerMCPClient(
            {
                "automind": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "automind.mcp_server"],
                    "env": {**os.environ},
                }
            }
        )
        session = await stack.enter_async_context(client.session("automind"))
        return list(await load_mcp_tools(session))
    except Exception:
        traceback.print_exc()
        print("WARNING: MCP tools unavailable; analysts fall back to the deterministic summary.")
        return []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_domain()
    await db.init_db()
    async with AsyncExitStack() as stack:
        saver = await stack.enter_async_context(checkpointer())
        tools = await _mcp_tools(stack)
        hub.MCP_TOOLS[:] = tools
        bus = EventBus(EventRepo())
        messages = MessageRepo()
        app.state.mcp_tools = tools
        app.state.bus = bus
        app.state.messages = messages
        app.state.chats = ChatRepo()
        app.state.delete_thread = saver.adelete_thread  # chat deletion removes the saved conversation state
        app.state.cases = CaseRepo()
        app.state.turns = TurnRepo()
        app.state.runner = ChatRunner(
            hub.build_graph(saver, tools), live_ports(bus, load_prompts()), new_budget, messages=messages
        )
        try:  # spec 010 US8: the source registry starts from favourites, the 009 survey and learned domains
            seeded = await seed_if_empty()
            if seeded:
                print(f"source registry seeded: {seeded}")
        except Exception:  # noqa: BLE001 - research works without the registry
            traceback.print_exc()
        retention = asyncio.create_task(retention_loop())  # spec 003 FR-026; heartbeat "retention" (spec 010)
        stack.callback(retention.cancel)
        # Spec 011 (constitution XIII): the metrics snapshot, the registry review and the insight run are tasks of
        # the acquisition worker (python -m automind.acquisition.worker), not loops of this process.
        resumed = await app.state.runner.resume_incomplete()
        if resumed:
            print(f"resuming {len(resumed)} interrupted turn(s)")
        yield


app = FastAPI(title="AutoMind", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def owner_and_origin(request: Request, call_next: Any) -> Response:
    """The browser's anonymous owner (cookie set on the first response) and same-site changes only (api/access)."""
    s = settings()
    if request.method in access.CHANGES and not access.origin_ok(
        request.headers.get("origin"), request.headers.get("host"), s.allowed_origins
    ):
        return JSONResponse(status_code=403, content={"code": "origin_refused", "message": "Cross-site request."})
    token = request.cookies.get(access.COOKIE)
    fresh = access.owner_of(token) is None
    if fresh:
        token = access.new_token()
    request.state.owner = access.owner_of(token) if s.owner_isolation else None
    response: Response = await call_next(request)
    if fresh and s.owner_isolation:
        response.headers.append("set-cookie", access.cookie_header(token or "", request.url.scheme == "https"))
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(rest.router)
app.include_router(metrics_api.router)  # spec 010 FR-030
app.include_router(admin_api.router)  # spec 010 US4


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{rest:path}", include_in_schema=False)
async def admin_page(rest: str = "") -> Response:
    """The admin SPA view (spec 010 US4): the same built index.html; the page itself asks for the token."""
    index = settings().frontend_dist / "index.html"
    if not index.exists():
        return JSONResponse(status_code=404, content={"code": "no_frontend", "message": "Frontend not built."})
    return FileResponse(index)


@app.websocket("/ws/chat/{chat_id}")
async def chat(ws: WebSocket, chat_id: str) -> None:
    st, s = ws.app.state, settings()
    if not access.origin_ok(ws.headers.get("origin"), ws.headers.get("host"), s.allowed_origins):
        await ws.close(code=4403)  # a page on another site tried to open this chat (cross-site WebSocket)
        return
    token = ws.cookies.get(access.COOKIE)
    headers: list[tuple[bytes, bytes]] = []
    if access.owner_of(token) is None:
        token = access.new_token()
        headers = [(b"set-cookie", access.cookie_header(token, ws.url.scheme == "wss").encode())]
    owner = access.owner_of(token) if s.owner_isolation else None
    await chat_socket(ws, chat_id, st.runner, st.bus, st.chats, owner=owner, headers=headers)


if settings().frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings().frontend_dist, html=True), name="frontend")


def main() -> None:
    import uvicorn

    s = settings()
    uvicorn.run("automind.api.app:app", host=s.api_host, port=s.api_port)
