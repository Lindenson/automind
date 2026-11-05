"""Turn outcomes and the one feedback table (spec 010 US1, US2). The score comes from domain/outcome.py."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from automind.domain import outcome as oc
from automind.insight.metrics import prom

from .models import Feedback, Turn, TurnOutcome, now
from .session import sessionmaker

log = logging.getLogger(__name__)


def settings_version(models_yaml: str, prompts: Mapping[str, str]) -> str:
    """A short hash of the model per role and every prompt text: outcomes say which settings produced them."""
    h = hashlib.sha256(models_yaml.encode("utf-8"))
    for name in sorted(prompts):
        h.update(name.encode())
        h.update(prompts[name].encode("utf-8"))
    return h.hexdigest()[:16]


def _rescore(row: TurnOutcome, cfg: Mapping[str, Any]) -> None:
    sig = dict(row.signals or {})
    rating = sig.get("rating")
    counts = {k: v for k, v in sig.items() if isinstance(v, int | float) and k != "rating"}
    facts = oc.TurnFacts(status=row.status, action=row.action, relation_next=row.relation_next,
                         rating=int(rating) if rating else None, signals=counts)  # fmt: skip
    row.failure_classes = sorted(c.value for c in oc.classes(facts))
    row.score = oc.score(facts, cfg)
    row.updated_at = now()


class OutcomeRepo:
    def __init__(self, cfg: Mapping[str, Any], version: str | None = None) -> None:
        self.cfg = cfg
        self.version = version

    async def record(self, turn_id: str, chat_id: str, **fields: Any) -> None:
        """Create or update the outcome of a turn (a waiting turn is recorded again when it ends)."""
        signals: dict[str, Any] = dict(fields.pop("signals", {}) or {})
        async with sessionmaker()() as s:
            row = await s.get(TurnOutcome, turn_id)
            if row is None:
                row = TurnOutcome(turn_id=turn_id, chat_id=chat_id, signals={}, path=[], status="RUNNING",
                                  score=0.0, settings_version=self.version)  # fmt: skip
                s.add(row)
            before = set(row.failure_classes or [])
            for k, v in fields.items():
                if hasattr(row, k) and v is not None:
                    setattr(row, k, v)
            merged = dict(row.signals or {})
            for k, v in signals.items():  # signals added later (feedback) are kept
                merged[k] = v
            row.signals = merged
            _rescore(row, self.cfg)
            await s.commit()
            for c in set(row.failure_classes) - before:
                prom.inc("turn_failures", **{"class": c})

    async def patch_previous(self, chat_id: str, turn_id: str, relation: str | None, signals: dict[str, float]) -> None:
        """The next message tells how the previous answer landed (relation, corrections of the car)."""
        async with sessionmaker()() as s:
            cur = await s.get(Turn, turn_id)
            q = select(TurnOutcome).where(TurnOutcome.chat_id == chat_id, TurnOutcome.turn_id != turn_id)
            if cur is not None:
                q = q.where(TurnOutcome.created_at < cur.created_at)
            prev = (await s.execute(q.order_by(TurnOutcome.created_at.desc()).limit(1))).scalar_one_or_none()
            if prev is None:
                return
            before = set(prev.failure_classes or [])
            if relation and prev.relation_next is None:
                prev.relation_next = relation
            merged = dict(prev.signals or {})
            for k, v in signals.items():
                merged[k] = float(merged.get(k, 0) or 0) + float(v)
            prev.signals = merged
            _rescore(prev, self.cfg)
            await s.commit()
            for c in set(prev.failure_classes) - before:
                prom.inc("turn_failures", **{"class": c})

    async def add_signal(self, turn_id: str, key: str, amount: float = 1.0) -> None:
        async with sessionmaker()() as s:
            row = await s.get(TurnOutcome, turn_id)
            if row is None:
                return
            before = set(row.failure_classes or [])
            merged = dict(row.signals or {})
            if key == "rating":
                merged["rating"] = amount
            else:
                merged[key] = float(merged.get(key, 0) or 0) + amount
            row.signals = merged
            _rescore(row, self.cfg)
            await s.commit()
            for c in set(row.failure_classes) - before:
                prom.inc("turn_failures", **{"class": c})

    async def feedback(self, chat_id: str, kind: str, **fields: Any) -> str:
        text = fields.get("text")
        if isinstance(text, str):
            fields["text"] = text[:1000]
        async with sessionmaker()() as s:
            row = Feedback(chat_id=chat_id, kind=kind, **{k: v for k, v in fields.items() if hasattr(Feedback, k)})
            s.add(row)
            await s.commit()
            prom.inc("feedback", kind=kind)
            return row.id

    async def turn_of_message(self, message_id: str) -> str | None:
        from .models import ChatMessage  # noqa: PLC0415

        async with sessionmaker()() as s:
            m = await s.get(ChatMessage, message_id)
            return m.turn_id if m is not None else None
