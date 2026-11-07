"""The components' reputation (`component_reputation`, spec 011 FR-011): a share of a signal added in the caller's
transaction (the registry records the signal and its shares together), one component read, every one faded. The
rules are `domain.components`. A database failure becomes `ReputationStoreUnavailable`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from automind.acquisition.reputation.application.errors import ReputationStoreUnavailable
from automind.acquisition.reputation.domain.components import Weights, credited, faded
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import ComponentReputation, now
from automind.shared.infrastructure.db.session import sessionmaker

KEY_CHARS = 160
_store_errors = translate_errors(ReputationStoreUnavailable)


async def add(s: AsyncSession, kind: str, key: str, verdict: str, weight: float, half_life_days: float) -> Weights:
    """Give a component its share of a signal in the session `s` (the caller commits); returns its new weights."""
    row = await s.get(ComponentReputation, (kind, key))
    if row is None:
        row = ComponentReputation(kind=kind, key=key[:KEY_CHARS], right_w=0.0, wrong_w=0.0, acc_lb=0.0,
                                  decayed_at=now())  # fmt: skip
        s.add(row)
    w = credited(_weights(row), verdict, weight, now(), half_life_days)
    _store(row, w)
    return w


class ComponentRepo:
    """Every component's weights."""

    @_store_errors
    async def get(self, kind: str, key: str) -> Weights | None:
        """The component's weights, None when it has none."""
        async with sessionmaker()() as s:
            row = await s.get(ComponentReputation, (kind, key))
            return _weights(row) if row is not None else None

    @_store_errors
    async def decay_all(self, half_life_days: float) -> int:
        """Every component faded to now, in one transaction; returns how many."""
        async with sessionmaker()() as s:
            rows = list((await s.execute(select(ComponentReputation))).scalars())
            t = now()
            for r in rows:
                _store(r, faded(_weights(r), t, half_life_days))
            await s.commit()
            return len(rows)

    @_store_errors
    async def weights(self) -> list[tuple[str, Weights]]:
        """Every component's (kind, weights)."""
        async with sessionmaker()() as s:
            return [(r.kind, _weights(r)) for r in (await s.execute(select(ComponentReputation))).scalars()]


def _weights(row: ComponentReputation) -> Weights:
    return Weights(float(row.right_w or 0.0), float(row.wrong_w or 0.0), row.decayed_at, float(row.acc_lb or 0.0))


def _store(row: ComponentReputation, w: Weights) -> None:
    row.right_w, row.wrong_w, row.decayed_at, row.acc_lb = w.right_w, w.wrong_w, w.decayed_at or now(), w.acc_lb
