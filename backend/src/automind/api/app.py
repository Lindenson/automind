"""FastAPI app: composition root. Wires config, DB, checkpointer, MCP tools, ports and the ChatRunner.

Endpoints: WebSocket `/ws/chat/{chat_id}` (protocol v2, api/ws.py), REST `/api/v1/*` (api/rest.py),
and the built frontend.
"""

from __future__ import annotations

import os
import sys
import traceback
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from automind.api import rest
from automind.api.ws import chat_socket
from automind.config import settings
from automind.infrastructure import db
from automind.infrastructure.adapters import live_ports
from automind.infrastructure.checkpoint import checkpointer
from automind.infrastructure.config import configure_domain
from automind.infrastructure.db.repositories import CaseRepo, ChatRepo, EventRepo, MessageRepo, TurnRepo
from automind.infrastructure.events import EventBus
from automind.infrastructure.llm_gateway import new_budget
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
        app.state.cases = CaseRepo()
        app.state.turns = TurnRepo()
        app.state.runner = ChatRunner(
            hub.build_graph(saver, tools), live_ports(bus, load_prompts()), new_budget, messages=messages
        )
        resumed = await app.state.runner.resume_incomplete()
        if resumed:
            print(f"resuming {len(resumed)} interrupted turn(s)")
        yield


app = FastAPI(title="AutoMind", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(rest.router)


@app.websocket("/ws/chat/{chat_id}")
async def chat(ws: WebSocket, chat_id: str) -> None:
    st = ws.app.state
    await chat_socket(ws, chat_id, st.runner, st.bus, st.chats)


if settings().frontend_dist.exists():
    app.mount("/", StaticFiles(directory=settings().frontend_dist, html=True), name="frontend")


def main() -> None:
    import uvicorn

    s = settings()
    uvicorn.run("automind.api.app:app", host=s.api_host, port=s.api_port)
