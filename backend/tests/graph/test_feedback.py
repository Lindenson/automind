"""Spec 010 US2 (T021): every user signal lands in one feedback table and moves the turn's outcome."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from automind.chat.application.usecases import challenge
from automind.chat.dialog.prompts import load_all
from automind.delivery.bootstrap import reference
from automind.delivery.web.ws import _BAD_SOURCE_LOG, ChatSocket
from automind.observability.infrastructure.outcomes import OutcomeRepo
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

from .conftest import open_web_reference
from .test_challenge import _claims
from .test_research_flow import fresh_variant as fresh_variant  # noqa: F401  (fixture)


class Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, chat_id: str, turn_id: Any, type_: str, payload: dict[str, Any]) -> None:
        self.events.append((type_, payload))


class Runner:
    def __init__(self, outcomes: OutcomeRepo) -> None:
        self.ports = type("P", (), {"outcomes": outcomes, "ref": open_web_reference()})()


async def _chat_with_turn() -> tuple[str, str, str, OutcomeRepo]:
    chat, turn, msg = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    async with sessionmaker()() as s:
        s.add(m.Chat(id=chat))
        await s.flush()
        s.add(m.Turn(id=turn, chat_id=chat, seq=1, status="DONE", action="REPORT"))
        s.add(m.ChatMessage(id=msg, chat_id=chat, turn_id=turn, role="assistant", text="report", blocks=[]))
        await s.commit()
    repo = OutcomeRepo(reference(load_all()).outcome, "test")
    await repo.record(turn, chat, status="DONE", action="REPORT", request_kind="compare")
    return chat, turn, msg, repo


async def _rows(chat: str) -> tuple[list[m.Feedback], m.TurnOutcome | None]:
    async with sessionmaker()() as s:
        fb = list((await s.execute(select(m.Feedback).where(m.Feedback.chat_id == chat))).scalars())
        out = (await s.execute(select(m.TurnOutcome).where(m.TurnOutcome.chat_id == chat))).scalar_one_or_none()
        return fb, out


def _socket(chat: str, repo: OutcomeRepo) -> tuple[ChatSocket, Bus]:
    bus = Bus()
    sock = ChatSocket(None, chat, Runner(repo), bus, None)  # type: ignore[arg-type]
    sock.ready.set()
    return sock, bus


async def test_rating_with_note_is_feedback_and_scores_the_turn():
    chat, turn, msg, repo = await _chat_with_turn()
    sock, _ = _socket(chat, repo)
    await sock._handle({"type": "rating", "message_id": msg, "rating": 2, "note": "missing maintenance"})  # noqa: SLF001
    fb, out = await _rows(chat)
    assert [(f.kind, f.rating, f.turn_id, f.text) for f in fb] == [("rating", 2, turn, "missing maintenance")]
    assert out is not None and out.score == 0.25


async def test_bad_source_is_feedback_and_wrong_data_and_rate_limited():
    chat, turn, msg, repo = await _chat_with_turn()
    sock, bus = _socket(chat, repo)
    await sock._handle({"type": "bad_source", "message_id": msg, "url": "https://junk.example/prado",  # noqa: SLF001
                        "car_id": "v1", "attribute": "used_price", "area": "used_price"})  # fmt: skip
    fb, out = await _rows(chat)
    assert [(f.kind, f.domain, f.attribute, f.turn_id) for f in fb] == [
        ("bad_source", "junk.example", "used_price", turn)
    ]
    assert out is not None and "wrong_data" in out.failure_classes
    assert bus.events[-1] == ("feedback_ack", {"kind": "bad_source", "url": "https://junk.example/prado"})
    await sock._handle({"type": "bad_source", "message_id": msg, "url": "not a url"})  # noqa: SLF001
    assert bus.events[-1][1].get("ignored") is True
    _BAD_SOURCE_LOG[chat] = [__import__("time").monotonic()] * 20
    await sock._handle({"type": "bad_source", "message_id": msg, "url": "https://other.example/x"})  # noqa: SLF001
    assert bus.events[-1][1].get("ignored") is True
    fb, _ = await _rows(chat)
    assert len(fb) == 1


@pytest.mark.usefixtures("fresh_variant")
async def test_challenge_names_turn_and_claim_and_is_feedback():
    chat, turn, _, repo = await _chat_with_turn()
    vid = await _claims(("1580", "Maletero 1580 litros", "Maletero 580 litros"))
    r = await challenge.recheck(open_web_reference(), chat, vid, "boot_volume", "wrong for this version")
    assert r["outcome"] == "REMOVED" and r["turn_id"] == turn and r["claim_id"]
    async with sessionmaker()() as s:
        vc = (await s.execute(select(m.ValueChallenge).where(m.ValueChallenge.chat_id == chat))).scalar_one()
    assert vc.turn_id == turn and vc.claim_id == r["claim_id"]
    sock, _ = _socket(chat, repo)
    await sock._challenge_feedback({"text": "wrong for this version"}, r)  # noqa: SLF001
    fb, out = await _rows(chat)
    assert [(f.kind, f.outcome, f.claim_id, f.text) for f in fb] == [
        ("wrong_value", "REMOVED", r["claim_id"], "wrong for this version")
    ]
    assert out is not None and "wrong_data" in out.failure_classes
