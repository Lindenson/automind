"""Chat WebSocket, protocol v2 (contracts/chat-protocol.md).

Client → server: hello{last_seq} | user_message{message_id, text} | confirm{request_id, choice, text?} | cancel.
Server → client: every event from the EventBus, each with `seq` and `turn_id`. Turns run as
background tasks, so a long research never blocks this connection, and a reconnecting client
replays everything after its `last_seq`.
"""

from __future__ import annotations

import asyncio
import contextlib
import traceback
from collections.abc import Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from automind.orchestration.runner import Busy, ChatRunner


class ChatSocket:
    def __init__(self, ws: WebSocket, chat_id: str, runner: ChatRunner, bus: Any, chats: Any) -> None:
        self.ws, self.chat_id, self.runner, self.bus, self.chats = ws, chat_id, runner, bus, chats
        self.sent_seq = 0
        self.ready = asyncio.Event()  # live events wait until the client's hello/replay is done
        self.tasks: set[asyncio.Task[Any]] = set()
        self.queue: asyncio.Queue[dict[str, Any]] | None = None

    async def serve(self) -> None:
        await self.ws.accept()
        is_deleted = getattr(self.chats, "is_deleted", None)
        if is_deleted is not None and await is_deleted(self.chat_id):  # FR-030: never recreate a deleted chat
            await self.ws.send_json({"type": "error", "code": "chat_deleted", "text": "This chat was deleted."})
            await self.ws.close(code=4410)
            return
        await self.chats.ensure(self.chat_id)
        self.queue = self.bus.subscribe(self.chat_id)  # subscribe before replay: nothing falls in between
        pumper = asyncio.create_task(self._pump())
        try:
            while True:
                await self._handle(await self.ws.receive_json())
        except WebSocketDisconnect:
            pass
        finally:
            pumper.cancel()
            self.bus.unsubscribe(self.chat_id, self.queue)
            # turns keep running in the background; their events are persisted for replay

    async def _handle(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "hello":
            for ev in await self.bus.replay(self.chat_id, int(msg.get("last_seq") or 0)):
                await self._send(ev)
            self.ready.set()
            return
        self.ready.set()  # a v1 client that never says hello still gets live events
        if kind == "user_message":
            text = str(msg.get("text", "")).strip()[:2000]
            if text:
                await self.chats.title_from_first_message(self.chat_id, text)
                self._background(self.runner.run_turn(self.chat_id, text, msg.get("message_id")))
        elif kind == "confirm":
            payload = {"choice": msg.get("choice"), "text": msg.get("text"), "request_id": msg.get("request_id")}
            self._background(self.runner.resume(self.chat_id, payload))
        elif kind == "cancel":
            await self.runner.cancel(self.chat_id)

    async def _send(self, msg: dict[str, Any]) -> None:
        seq = msg.get("seq")
        if isinstance(seq, int):
            if seq <= self.sent_seq:
                return  # already delivered by replay
            self.sent_seq = seq
        await self.ws.send_json(msg)

    async def _pump(self) -> None:
        await self.ready.wait()
        assert self.queue is not None
        while True:
            await self._send(await self.queue.get())

    def _background(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(self._guard(coro))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _guard(self, coro: Coroutine[Any, Any, Any]) -> None:
        try:
            await coro
        except Busy:
            await self._error("busy: a turn is already running in this chat")
        except Exception as e:  # reported to the client; the connection stays open
            traceback.print_exc()
            await self._error(f"{type(e).__name__}: {e}"[:500])

    async def _error(self, text: str) -> None:
        with contextlib.suppress(Exception):
            await self.ws.send_json({"type": "error", "text": text})


async def chat_socket(ws: WebSocket, chat_id: str, runner: ChatRunner, bus: Any, chats: Any) -> None:
    await ChatSocket(ws, chat_id, runner, bus, chats).serve()
