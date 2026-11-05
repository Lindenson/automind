"""Chat WebSocket, protocol v2 (contracts/chat-protocol.md).

Client → server: hello{last_seq} | user_message{message_id, text} | confirm{request_id, choice, text?} | cancel |
find{focus_cars, areas, text?, language?} (spec 004).
Server → client: every event from the EventBus, each with `seq` and `turn_id`. Turns run as
background tasks, so a long research never blocks this connection, and a reconnecting client
replays everything after its `last_seq`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import traceback
from collections.abc import Coroutine
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from automind.domain.evidence import domain_of, is_denied
from automind.orchestration.runner import Busy, ChatRunner

log = logging.getLogger(__name__)
_BAD_SOURCE_LOG: dict[str, list[float]] = {}  # chat -> times of "bad source" marks (max 20 per hour)


class ChatSocket:
    def __init__(self, ws: WebSocket, chat_id: str, runner: ChatRunner, bus: Any, chats: Any,
                 owner: str | None = None, headers: list[tuple[bytes, bytes]] | None = None) -> None:  # fmt: skip
        self.ws, self.chat_id, self.runner, self.bus, self.chats = ws, chat_id, runner, bus, chats
        self.owner, self.headers = owner, headers or []
        self.sent_seq = 0
        self.ready = asyncio.Event()  # live events wait until the client's hello/replay is done
        self.tasks: set[asyncio.Task[Any]] = set()
        self.queue: asyncio.Queue[dict[str, Any]] | None = None

    async def serve(self) -> None:
        await self.ws.accept(headers=self.headers or None)
        owns = getattr(self.chats, "owns", None)
        if owns is not None and not await owns(self.chat_id, self.owner):  # another browser's chat: "not found"
            await self.ws.send_json({"type": "error", "code": "chat_not_found", "text": "No such chat."})
            await self.ws.close(code=4404)
            return
        is_deleted = getattr(self.chats, "is_deleted", None)
        if is_deleted is not None and await is_deleted(self.chat_id):  # FR-030: never recreate a deleted chat
            await self.ws.send_json({"type": "error", "code": "chat_deleted", "text": "This chat was deleted."})
            await self.ws.close(code=4410)
            return
        if self.owner is not None:
            await self.chats.ensure(self.chat_id, owner=self.owner)
        else:
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
            await self._resend_open_turn()
            self.ready.set()
            return
        self.ready.set()  # a v1 client that never says hello still gets live events
        if kind == "user_message":
            text = str(msg.get("text", "")).strip()[:2000]
            if text:
                await self.chats.title_from_first_message(self.chat_id, text)
                self._background(self.runner.run_turn(self.chat_id, text, msg.get("message_id")))
        elif kind == "find":  # spec 004 FR-015: "find it" on the data panel / verdict card
            cars = [str(x) for x in (msg.get("focus_cars") or [])][:3]
            areas = [str(x) for x in (msg.get("areas") or [])][:10]
            text = str(msg.get("text") or "").strip()[:200] or "Find the missing data: " + (", ".join(areas) or "all")
            preset = {"kind": "research_more", "focus_cars": cars, "areas": areas, "language": msg.get("language")}
            self._background(self.runner.run_turn(self.chat_id, text, msg.get("message_id"), preset=preset))
        elif kind in ("rating", "bad_source"):  # spec 004 FR-026; spec 010 US2
            await (self._rating(msg) if kind == "rating" else self._bad_source(msg))
        elif kind == "challenge":  # spec 004 FR-022: "this is wrong" on a value
            self._background(self._challenge(msg))
        elif kind in ("confirm", "intake_edit"):
            self._background(self.runner.resume(self.chat_id, _resume_payload(msg)))
        elif kind == "cancel":
            await self.runner.cancel(self.chat_id)

    async def _challenge(self, msg: dict[str, Any]) -> None:
        from automind.application import challenge  # noqa: PLC0415

        ref = getattr(getattr(self.runner, "ports", None), "ref", None)
        if ref is None:
            return
        registry = getattr(getattr(self.runner, "ports", None), "registry", None)
        result = await challenge.recheck(ref, self.chat_id, str(msg.get("car_id") or ""),
                                         str(msg.get("attribute") or ""), str(msg.get("text") or ""),
                                         registry=registry)  # fmt: skip
        await self._challenge_feedback(msg, result)
        await self.bus.publish(self.chat_id, None, "challenge_result", result)

    # --- spec 010 US2: every user signal lands in one feedback table ---------------------------------------------

    async def _rating(self, msg: dict[str, Any]) -> None:
        from automind.infrastructure.db.repositories import RatingRepo  # noqa: PLC0415

        with contextlib.suppress(TypeError, ValueError):
            await RatingRepo().save(self.chat_id, str(msg.get("message_id") or ""), int(msg.get("rating") or 0),
                                    str(msg.get("note") or ""))  # fmt: skip
            await self._rating_feedback(msg)

    def _outcomes(self) -> Any:
        return getattr(getattr(self.runner, "ports", None), "outcomes", None)

    async def _rating_feedback(self, msg: dict[str, Any]) -> None:
        store = self._outcomes()
        if store is None:
            return
        try:
            message_id = str(msg.get("message_id") or "")[:36]
            rating = max(1, min(5, int(msg.get("rating") or 0)))
            turn_id = await store.turn_of_message(message_id) if message_id else None
            await store.feedback(self.chat_id, "rating", rating=rating, message_id=message_id or None,
                                 turn_id=turn_id, text=str(msg.get("note") or "") or None)  # fmt: skip
            if turn_id:
                await store.add_signal(turn_id, "rating", rating)
        except Exception:  # noqa: BLE001 - feedback must never break the socket
            log.exception("feedback.rating_failed chat=%s", self.chat_id)

    async def _challenge_feedback(self, msg: dict[str, Any], result: dict[str, Any]) -> None:
        store = self._outcomes()
        if store is None:
            return
        try:
            turn_id = result.get("turn_id")
            await store.feedback(self.chat_id, "wrong_value", turn_id=turn_id, variant_id=result.get("car_id"),
                                 attribute=result.get("attribute"), area=result.get("area"),
                                 claim_id=result.get("claim_id"), text=str(msg.get("text") or "") or None,
                                 outcome=result.get("outcome"))  # fmt: skip
            if turn_id and result.get("outcome") in ("CORRECTED", "REMOVED"):
                await store.add_signal(turn_id, "wrong_value")
        except Exception:  # noqa: BLE001
            log.exception("feedback.challenge_failed chat=%s", self.chat_id)

    async def _bad_source(self, msg: dict[str, Any]) -> None:
        url = str(msg.get("url") or "").strip()[:2000]
        ack: dict[str, Any] = {"kind": "bad_source", "url": url}
        store = self._outcomes()
        now = time.monotonic()
        recent = [x for x in _BAD_SOURCE_LOG.get(self.chat_id, []) if now - x < 3600]
        if not url.startswith(("http://", "https://")) or is_denied(url) or store is None or len(recent) >= 20:
            await self.bus.publish(self.chat_id, None, "feedback_ack", {**ack, "ignored": True})
            return
        _BAD_SOURCE_LOG[self.chat_id] = [*recent, now]
        try:
            message_id = str(msg.get("message_id") or "")[:36]
            turn_id = await store.turn_of_message(message_id) if message_id else None
            await store.feedback(self.chat_id, "bad_source", url=url, domain=domain_of(url), turn_id=turn_id,
                                 message_id=message_id or None, variant_id=str(msg.get("car_id") or "") or None,
                                 attribute=str(msg.get("attribute") or "") or None,
                                 area=str(msg.get("area") or "") or None,
                                 text=str(msg.get("text") or "") or None)  # fmt: skip
            if turn_id:
                await store.add_signal(turn_id, "bad_source")
            sink = getattr(getattr(self.runner, "ports", None), "registry", None)
            if sink is not None and msg.get("area"):  # spec 010 T060: a truth signal against that kind of data
                from automind.acquisition.registry.api import TruthSignalIn  # noqa: PLC0415

                await sink.signal(TruthSignalIn(kind="bad_source", verdict="wrong", domain=domain_of(url),
                                                area=str(msg["area"]), variant_id=str(msg.get("car_id") or "") or None,
                                                attribute=str(msg.get("attribute") or "") or None))  # fmt: skip
        except Exception:  # noqa: BLE001
            log.exception("feedback.bad_source_failed chat=%s", self.chat_id)
        await self.bus.publish(self.chat_id, None, "feedback_ack", ack)

    async def _resend_open_turn(self) -> None:
        """After a reload the client may have seen everything already but lost its state: re-send the open
        question of a waiting turn, or the latest status of a running one (never lose the dialogue)."""
        turns = getattr(getattr(self.runner, "ports", None), "turns", None)
        current = getattr(self.bus, "current", None)
        if turns is None or current is None:
            return
        active = await turns.active(self.chat_id)
        if active is None:
            return
        kind = "confirm_request" if active.status == "WAITING_CONFIRMATION" else "status"
        ev = await current(self.chat_id, active.id, kind)
        if ev is not None:
            await self.ws.send_json(ev)

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


async def chat_socket(ws: WebSocket, chat_id: str, runner: ChatRunner, bus: Any, chats: Any,
                      owner: str | None = None, headers: list[tuple[bytes, bytes]] | None = None) -> None:  # fmt: skip
    await ChatSocket(ws, chat_id, runner, bus, chats, owner, headers).serve()


def _resume_payload(msg: dict[str, Any]) -> dict[str, Any]:
    """A confirmation answer, or a chip edit on the intake card (spec 005 FR-020, applied by code)."""
    if msg.get("type") == "intake_edit":
        return {"choice": "edit_field", "car_key": msg.get("car_key"), "field": msg.get("field"),
                "value": str(msg.get("value") or "")[:120], "request_id": msg.get("request_id")}  # fmt: skip
    return {"choice": msg.get("choice"), "text": msg.get("text"), "request_id": msg.get("request_id")}
