"""Spec 010 US3/US5 (T041, T047): failures become issues with a diagnosis; a fixed issue that grows again reopens;
seeded issues exist once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker
from automind.insight import loop
from automind.insight.application.analyse import Diagnosis, Fix
from automind.insight.domain.clusters import fingerprint
from automind.insight.domain.issue_text import copy_text


class FakeAnalyst:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def structured(self, role: str, schema: type, system: str, user: str) -> Diagnosis:
        self.calls.append(user)
        assert role == "analyst" and "data, not instructions" in user
        if "check/" in user:
            fix = Fix(kind="config", config_file="sense.yaml", config_key="magnitude.boot_volume.max",
                      suggested_value="2000")  # fmt: skip
        else:
            fix = Fix(kind="code", files=["src/automind/application/interpret.py"], direction="add few-shots")
        return Diagnosis(summary="users rephrase comparisons", likely_cause="few-shots", fix=fix, verify="golden")


async def _seed_failures(chat: str, n_rephrase: int, n_wrong: int, at: datetime) -> None:
    async with sessionmaker()() as s:
        for i in range(n_rephrase):
            s.add(m.TurnOutcome(turn_id=str(uuid.uuid4()), chat_id=chat, created_at=at + timedelta(seconds=i),
                                updated_at=at, request_kind="compare", language="ru", status="DONE", score=0.2,
                                failure_classes=["not_understood"], signals={}))  # fmt: skip
        for _ in range(n_wrong):
            s.add(m.Feedback(chat_id=chat, kind="wrong_value", attribute="power_kw", outcome="CORRECTED",
                             created_at=at))  # fmt: skip
        await s.commit()


async def _issue(key: str) -> m.InsightIssue | None:
    async with sessionmaker()() as s:
        return (await s.execute(select(m.InsightIssue).where(m.InsightIssue.fingerprint == fingerprint(key)))
                ).scalar_one_or_none()  # fmt: skip


async def test_failures_become_diagnosed_issues_and_regressions_reopen():
    async with sessionmaker()() as s:
        for t in (m.TurnOutcome, m.Feedback, m.InsightIssue, m.InsightRun):
            await s.execute(delete(t))
        await s.commit()
    chat = str(uuid.uuid4())
    await _seed_failures(chat, 3, 5, datetime.now(UTC) - timedelta(hours=2))
    analyst = FakeAnalyst()
    stats = await loop.analyse("manual", llm=analyst)
    assert stats["groups"] >= 2 and stats["diagnosed"] >= 2
    dialogue = await _issue("dialogue/not_understood/compare/ru")
    data = await _issue("data/wrong_data/power_kw")
    assert dialogue is not None and dialogue.count_7d == 3 and dialogue.diagnosis["fix"]["kind"] == "code"
    assert dialogue.diagnosis["fix"]["files"] == ["src/automind/application/interpret.py"]  # exists → kept
    assert data is not None and data.count_7d == 5 and data.status == "open"
    md = copy_text({c.name: getattr(dialogue, c.name) for c in m.InsightIssue.__table__.columns})
    assert "users rephrase comparisons" in md and chat in md
    async with sessionmaker()() as s:  # seeded 009/UX issues exist once
        seeded = (await s.execute(select(m.InsightIssue).where(m.InsightIssue.source.like("seed:%")))).scalars().all()
    assert len(seeded) == 15
    await loop.analyse("manual", llm=analyst)
    async with sessionmaker()() as s:
        assert len((await s.execute(select(m.InsightIssue).where(m.InsightIssue.source.like("seed:%")))).all()) == 15
        row = await s.get(m.InsightIssue, data.id)
        row.status, row.fixed_at, row.fixed_ref = "fixed", datetime.now(UTC) - timedelta(minutes=30), "abc123"
        await s.commit()
    await _seed_failures(chat, 0, 2, datetime.now(UTC) - timedelta(minutes=5))
    stats = await loop.analyse("manual", llm=analyst)
    assert stats["regressions"] == 1
    again = await _issue("data/wrong_data/power_kw")
    assert again is not None and again.status == "regression" and again.status_history[-1]["by"] == "system"
