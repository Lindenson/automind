""" "This is wrong" on a value (spec 004 FR-022; research R10).

The accepted claims behind the value are checked again against their documents with the current rules
(excerpt, unit, plausibility, sense, gearbox/drive of the variant). Claims that fail are rejected; the value is
selected again. Outcome:
- CONFIRMED: every claim passes and ≥ 2 independent sources agree;
- CORRECTED: some claims failed and another value is now selected;
- REMOVED: every claim failed: the value is gone;
- UNRESOLVED: one source only (or none): a fresh search for the area is suggested ("find it").
Stored in value_challenges with the details. No model call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from automind.acquisition import api as acquisition
from automind.shared.contracts.config import Reference
from automind.shared.infrastructure import db
from automind.shared.vehicle import specs

GoldSink = Callable[..., Awaitable[bool]]  # acquisition.api.record_challenge_gold (spec 011 T027)


async def recheck(
    ref: Reference, chat_id: str, variant_id: str, attribute: str, user_text: str = "", registry: Any = None,
    gold: GoldSink | None = None,
) -> dict[str, Any]:  # fmt: skip
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        if v is None or attribute not in specs.ATTRS:
            return {"outcome": "UNRESOLVED", "text": "unknown value", "attribute": attribute}
        before = (
            await s.execute(
                select(db.SpecValue).where(db.SpecValue.variant_id == variant_id, db.SpecValue.attribute == attribute)
            )
        ).scalar_one_or_none()
        old = _shown(attribute, before)
    checked = await acquisition.recheck_value(variant_id, attribute, rules=ref.plausibility)
    rejected, kept, claim_id = checked.rejected, checked.kept, checked.claim_id
    judged = [(j.domain, j.area, j.claim_id, j.excerpt, j.by, j.ok) for j in checked.judged]
    async with db.sessionmaker()() as s:
        after = (
            await s.execute(
                select(db.SpecValue).where(db.SpecValue.variant_id == variant_id, db.SpecValue.attribute == attribute)
            )
        ).scalar_one_or_none()
        new = _shown(attribute, after)
        sources = sorted(set(kept))
        if not kept:
            outcome = "REMOVED" if rejected else "UNRESOLVED"
        elif rejected and new != old:
            outcome = "CORRECTED"
        elif len(sources) >= 2:
            outcome = "CONFIRMED"
        else:
            outcome = "UNRESOLVED"
        details = {"before": old, "after": new, "rejected": rejected, "sources": sources}
        turn_id = challenge_id = None
        if await s.get(db.Chat, chat_id) is not None:  # chat-scoped record (deleted with the chat)
            turn_id = (
                await s.execute(
                    select(db.Turn.id)
                    .where(db.Turn.chat_id == chat_id, db.Turn.status == "DONE")
                    .order_by(db.Turn.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            row = db.ValueChallenge(chat_id=chat_id, variant_id=variant_id, attribute=attribute, turn_id=turn_id,
                                    claim_id=claim_id, user_text=user_text[:500], outcome=outcome,
                                    details=details)  # fmt: skip
            s.add(row)
            await s.commit()
            challenge_id = row.id
    area = specs.ATTRS[attribute].category
    await _signals(registry, outcome, judged, new, variant_id, attribute)
    if gold is not None:  # spec 011 FR-003: a confirmed or corrected value is a reference value for this variant
        await gold(variant_id, attribute, outcome, new, challenge_id=challenge_id)
    return {"outcome": outcome, "attribute": attribute, "car_id": variant_id, "area": area, **details,
            "turn_id": turn_id, "claim_id": claim_id}  # fmt: skip


def _shown(attribute: str, sv: Any) -> str | None:
    if sv is None or not sv.available:
        return None
    return str(sv.value_text if sv.value_text is not None else sv.value_num)


async def _signals(registry: Any, outcome: str, judged: list[tuple[str, str, str, str | None, str | None, bool]],
                   corrected: str | None, variant_id: str, attribute: str) -> None:  # fmt: skip
    """Spec 010 T060: a challenge is a truth signal for the sources behind the value. A page that holds the right
    number but was misread blames our reader or extractor, not the source (FR-017)."""
    if registry is None or outcome == "UNRESOLVED":
        return
    from automind.acquisition.registry.api import TruthKind, TruthSignalIn, TruthVerdict, blame_challenge  # noqa: PLC0415

    async with db.sessionmaker()() as s:  # spec 011 R9: the producer version and model name the blamed reader
        made = {c.id: (c.producer_version, c.model) for c in (await s.execute(
            select(db.Claim).where(db.Claim.id.in_([j[2] for j in judged])))).scalars()}  # fmt: skip
    for domain, area, claim_id, excerpt, by, ok in judged:
        if outcome == "CONFIRMED" and ok:
            verdict, b = TruthVerdict.RIGHT, None
        elif not ok:  # spec 011 R9: vector blame; only the blamed component's reputation changes
            producer = made.get(claim_id, (None, None))
            verdict, b = TruthVerdict.WRONG, blame_challenge(corrected, excerpt, by, *producer, domain)
        else:
            continue
        await registry.signal(TruthSignalIn(kind=TruthKind.CHALLENGE, verdict=verdict, domain=domain, area=area,
                                            variant_id=variant_id, attribute=attribute, claim_id=claim_id,
                                            blame=b.label if b else "source", blame_vector=b.vector if b else None,
                                            components=b.components if b else {}))  # type: ignore[arg-type]  # fmt: skip
