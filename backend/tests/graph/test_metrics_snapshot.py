"""Spec 010 US9 (T027): the Prometheus snapshot reflects outcomes, feedback and the registry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from prometheus_client import generate_latest
from sqlalchemy import delete

from automind.observability.metrics import heartbeat, snapshot
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

NODATA = {"nodata_items": [{"car": "car#1", "area": "used_price"}]}


def _get(snap, name: str, labels: tuple[str, ...]) -> float | None:
    for lv, v in snap.values.get(name, []):
        if lv == labels:
            return v
    return None


async def test_snapshot_from_seeded_journals():
    chat = str(uuid.uuid4())
    dom = f"snap-{uuid.uuid4().hex[:6]}.example"
    async with sessionmaker()() as s:
        for t in (m.TurnOutcome, m.Feedback, m.TruthSignal, m.CapabilityRow):
            await s.execute(delete(t))
        now = datetime.now(UTC)
        for score, kind in ((0.2, "compare"), (0.6, "compare"), (1.0, "general_question")):
            s.add(m.TurnOutcome(turn_id=str(uuid.uuid4()), chat_id=chat, created_at=now, request_kind=kind,
                                action="REPORT", status="DONE", score=score, language="ru", persona="BUYER",
                                signals=NODATA if score < 1 else {}))  # fmt: skip
        for kind in ("complaint", "complaint", "bad_source", "rating"):
            s.add(m.Feedback(chat_id=chat, kind=kind))
        cap = m.CapabilityRow(domain=dom, area="specs", market="ES", status="active", score=0.7, acc_lb=0.8, yield_=0.5)
        s.add(cap)
        await s.flush()
        s.add(m.TruthSignal(capability_id=cap.id, kind="challenge", verdict="right", weight=1.0, blame="source"))
        s.add(m.TruthSignal(capability_id=cap.id, kind="challenge", verdict="wrong", weight=1.0, blame="source"))
        await s.commit()
    heartbeat.beat("insight", True, 600)
    snap = await snapshot.run_once()
    assert _get(snap, "satisfaction_index", ("compare", "7d")) == 0.4
    assert _get(snap, "satisfaction_turns", ("all", "7d")) == 3
    assert _get(snap, "satisfaction_index_by", ("language", "ru", "7d")) is not None
    assert abs((_get(snap, "nodata_share", ("used_price", "7d")) or 0) - 2 / 3) < 1e-9
    assert _get(snap, "complaints_24h", ("complaint",)) == 2
    assert _get(snap, "accuracy_share", ("specs", "7d")) == 0.5
    assert _get(snap, "source_wrong_values_24h", (dom,)) == 1
    assert _get(snap, "capabilities", ("specs", "active")) == 1
    assert _get(snap, "source_score", (dom, "specs", "ES")) == 0.7
    text = generate_latest().decode()
    assert 'automind_satisfaction_index{kind="compare",window="7d"} 0.4' in text
    assert 'automind_loop_last_success_timestamp_seconds{loop="insight"}' in text
