"""Agreement of independent source families on one value (spec 011 FR-010, research R7, US3 AS-3). Pure.

The consensus is the largest set of families whose values agree within the attribute's tolerance; with at least two
families each family gets one `agreement` signal (on the member whose value is closest to the consensus). Mirrors in
one family never reinforce each other, and two equally large disagreeing sets give no signal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyValue:
    claim_id: str
    domain: str
    family: str
    value: float


@dataclass(frozen=True)
class Agreement:
    family: str
    claim_id: str
    domain: str
    value: float
    families: int  # how many families agree


def _near(a: float, b: float, tol: tuple[str, float]) -> bool:
    kind, t = tol
    return abs(a - b) <= (t if kind == "abs" else t * abs(b)) + 1e-9


def agreements(values: Sequence[FamilyValue], tol: tuple[str, float]) -> list[Agreement]:
    clusters: dict[frozenset[str], float] = {}
    for pivot in values:
        fams = frozenset(v.family for v in values if _near(v.value, pivot.value, tol))
        clusters.setdefault(fams, pivot.value)
    if not clusters:
        return []
    best = max(len(f) for f in clusters)
    tops = [f for f in clusters if len(f) == best]
    if best < 2 or len({f for f in tops}) != 1:
        return []
    fams, centre = tops[0], clusters[tops[0]]
    out: list[Agreement] = []
    for fam in sorted(fams):
        members = [v for v in values if v.family == fam and _near(v.value, centre, tol)]
        if not members:
            continue
        m = min(members, key=lambda v: (abs(v.value - centre), v.domain, v.claim_id))
        out.append(Agreement(fam, m.claim_id, m.domain, m.value, len(fams)))
    return out
