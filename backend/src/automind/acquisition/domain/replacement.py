"""Later replacement of a shown value by a more confident one (spec 010 T060, spec 011 FR-010). Pure.

Read after the fact from the stored claims: a claim that was the only accepted claim of its attribute (so it was the
shown value) and that disagrees with today's selection, made of claims that all came later, was replaced. Found
from the tables, without a hook in the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from automind.acquisition.domain.tolerance import within


@dataclass(frozen=True)
class Seen:
    claim_id: str
    domain: str
    value: float
    order: float  # creation time (any increasing number)


def _near(a: float, b: float, tol: tuple[str, float]) -> bool:
    return within(a, b, tol)


def replaced(
    history: Sequence[Seen], selected_ids: Iterable[str], selected: float, tol: tuple[str, float]
) -> list[Seen]:
    sel = set(selected_ids)
    chosen = [s for s in history if s.claim_id in sel]
    if not chosen:
        return []
    first_selected = min(s.order for s in chosen)
    out = []
    for s in history:
        if s.claim_id in sel or s.order >= first_selected or _near(s.value, selected, tol):
            continue
        alone = not any(o.claim_id != s.claim_id and o.order <= s.order for o in history)
        if alone:
            out.append(s)
    return out
