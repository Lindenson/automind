"""Reputation of the pipeline components vector blame can name (spec 011 FR-011, research R9, data-model 0021).

`add()` gives a component its share of a signal in the caller's session (decayed to now first); `decay_all()` is the
daily fade run by the roll-up. Keys: `parser:km77@v1`, `extractor:extract_specs@v3|<model>`, `rule:units.ps_kw`,
`fusion:merge@1`, `relevance:<method>`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from automind.acquisition.registry.domain.score import decay, wilson_lb
from automind.infrastructure.db.models import ComponentReputation, now
from automind.infrastructure.db.session import sessionmaker


def _fade(row: ComponentReputation, hl: float) -> None:
    t = now()
    days = (t - row.decayed_at).total_seconds() / 86400 if row.decayed_at else 0.0
    if days > 0:
        row.right_w = decay(float(row.right_w or 0.0), days, hl)
        row.wrong_w = decay(float(row.wrong_w or 0.0), days, hl)
    row.decayed_at = t
    row.acc_lb = wilson_lb(float(row.right_w or 0.0), float(row.wrong_w or 0.0))


async def add(s: Any, kind: str, key: str, verdict: str, weight: float, hl: float) -> ComponentReputation:
    row = await s.get(ComponentReputation, (kind, key))
    if row is None:
        row = ComponentReputation(kind=kind, key=key[:160], right_w=0.0, wrong_w=0.0, acc_lb=0.0, decayed_at=now())
        s.add(row)
    _fade(row, hl)
    if verdict == "right":
        row.right_w += weight
    else:
        row.wrong_w += weight
    row.acc_lb = wilson_lb(row.right_w, row.wrong_w)
    return row


async def get(kind: str, key: str) -> ComponentReputation | None:
    async with sessionmaker()() as s:
        return await s.get(ComponentReputation, (kind, key))


async def decay_all(hl: float) -> int:
    async with sessionmaker()() as s:
        rows = list((await s.execute(select(ComponentReputation))).scalars())
        for r in rows:
            _fade(r, hl)
        await s.commit()
        return len(rows)


async def acc_lb_by_kind() -> dict[str, float]:
    """Weighted mean lower bound per component kind (the `automind_component_acc_lb{kind}` gauge)."""
    async with sessionmaker()() as s:
        rows = list((await s.execute(select(ComponentReputation))).scalars())
    out: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        out.setdefault(r.kind, []).append((r.acc_lb, r.right_w + r.wrong_w))
    return {k: (sum(a * w for a, w in v) / sum(w for _, w in v)) if sum(w for _, w in v) > 0 else 0.0
            for k, v in out.items()}  # fmt: skip
