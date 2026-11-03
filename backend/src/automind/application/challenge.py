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

from typing import Any

from sqlalchemy import select

from automind.application import research as rs
from automind.application.ports import Reference, WebDoc
from automind.domain import specs
from automind.infrastructure import db


async def recheck(ref: Reference, chat_id: str, variant_id: str, attribute: str, user_text: str = "") -> dict[str, Any]:
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
        rows = (
            await s.execute(
                select(db.Claim, db.Evidence, db.Document)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .join(db.Document, db.Evidence.document_id == db.Document.id)
                .where(
                    db.Claim.variant_id == variant_id, db.Claim.attribute == attribute, db.Claim.status == "ACCEPTED"
                )
            )
        ).all()
        rejected, kept = [], []
        ctx = rs._plausibility_ctx(v, {})  # noqa: SLF001 - the research-time rules
        for c, e, d in rows:
            claim = rs._ReaderClaim(c.attribute, c.raw_value, c.raw_unit, c.excerpt)  # noqa: SLF001
            doc = WebDoc(e.url, d.title or "", d.text or "", bool(e.snippet_only))
            status, _, _, rule = rs._check(claim, doc, ctx, ref.plausibility)  # noqa: SLF001
            if status != "ACCEPTED":
                c.status, c.reject_rule = status, rule or "challenge"
                rejected.append({"source": e.domain, "value": c.raw_value, "why": status.lower()})
            else:
                kept.append(e.domain)
        await s.commit()
    await rs.reselect(variant_id)
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
        if await s.get(db.Chat, chat_id) is not None:  # chat-scoped record (deleted with the chat)
            s.add(db.ValueChallenge(chat_id=chat_id, variant_id=variant_id, attribute=attribute,
                                    user_text=user_text[:500], outcome=outcome, details=details))  # fmt: skip
            await s.commit()
    area = specs.ATTRS[attribute].category
    return {"outcome": outcome, "attribute": attribute, "car_id": variant_id, "area": area, **details}


def _shown(attribute: str, sv: Any) -> str | None:
    if sv is None or not sv.available:
        return None
    return str(sv.value_text if sv.value_text is not None else sv.value_num)
