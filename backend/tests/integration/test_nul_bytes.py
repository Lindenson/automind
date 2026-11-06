"""A web page with a NUL character must not crash a turn (2026-11-06, Deepal S09 vs Li L9)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from automind.infrastructure.db import Document, sessionmaker
from automind.infrastructure.db.models import TurnOutcome


async def test_nul_in_text_and_json_is_stripped_on_write():
    url = f"https://nul.example/{uuid.uuid4().hex}"
    async with sessionmaker()() as s:
        s.add(Document(url=url, title="Li\x00 L9", text="power 330\x00 kW", content_sha256=uuid.uuid4().hex))
        tid = str(uuid.uuid4())
        s.add(TurnOutcome(turn_id=tid, chat_id=str(uuid.uuid4()), status="DONE", score=0.5,
                          signals={"quote": "a\x00b"}))  # fmt: skip
        await s.commit()
    async with sessionmaker()() as s:
        d = (await s.execute(select(Document).where(Document.url == url))).scalar_one()
        o = await s.get(TurnOutcome, tid)
        assert d.title == "Li L9" and d.text == "power 330 kW"
        assert o is not None and o.signals["quote"] == "ab"
        await s.execute(delete(Document).where(Document.url == url))
        await s.execute(delete(TurnOutcome).where(TurnOutcome.turn_id == tid))
        await s.commit()
