"""The decisions of the daily review (spec 010 US7, T066). Pure: the capabilities come in faded and rescored.

For each capability the lifecycle proposes a move (domain/lifecycle.py); the hard limits (domain/limits.py) apply,
hold (a frozen source: journalled, not applied) or refuse it. Every applied or held move is a journal entry; a
re-ordering among the first `TOP_RANKS` of an area and market by at least two places is journalled too.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from automind.acquisition.registry.domain import limits
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.lifecycle import CapState, transition
from automind.acquisition.registry.domain.records import JournalEntry, ReviewedCapability, SourceState, StatusMove

TOP_RANKS = 10  # re-ordering is journalled for the first ranks of each kind of data
MIN_RANK_SHIFT = 2
RANKED = ("active", "candidate", "degraded")
CHANGE_OF_MOVE = {"active": "promoted", "degraded": "demoted", "retired": "retired", "blocked": "blocked"}


@dataclass(frozen=True)
class ReviewFacts:
    """What the review reads besides the capabilities: the sources' access and freeze, the owner's reverts."""

    sources: Mapping[str, SourceState] = field(default_factory=dict)
    reverts: Mapping[str, datetime] = field(default_factory=dict)  # capability id → last owner revert
    deny: Sequence[str] = ()


@dataclass(frozen=True)
class ReviewPlan:
    """The moves to apply and the journal to write, in order; `stats` counts changes, held, refused, reordered."""

    moves: tuple[StatusMove, ...]
    journal: tuple[JournalEntry, ...]
    stats: dict[str, int]


def plan_review(caps: Sequence[ReviewedCapability], facts: ReviewFacts, cfg: RegistryConfig,
                now: datetime) -> ReviewPlan:  # fmt: skip
    """The status moves and journal entries of one review run."""
    stats = {"changes": 0, "held": 0, "refused": 0, "reordered": 0}
    moves: list[StatusMove] = []
    journal: list[JournalEntry] = []
    for c in caps:
        decided = _decide(c, facts, cfg, now)
        if decided is None:
            continue
        verdict, entry = decided
        if verdict == "refused":
            stats["refused"] += 1
            continue
        journal.append(entry)
        if verdict == "held":
            stats["held"] += 1
            continue
        moves.append(StatusMove(c.id, str(entry.after["status"])))
        stats["changes"] += 1
    reorders = _reorders(caps, {m.capability_id: m.to for m in moves})
    stats["reordered"] = len(reorders)
    return ReviewPlan(tuple(moves), (*journal, *reorders), stats)


def ranks(
    caps: Sequence[ReviewedCapability], status: Mapping[str, str], score_of: Mapping[str, float]
) -> dict[str, int]:
    """Rank of each ranked capability within its area and market: active first, then by score."""
    by_area: dict[str, list[ReviewedCapability]] = defaultdict(list)
    for c in caps:
        if status[c.id] in RANKED:
            by_area[f"{c.area}|{c.market}"].append(c)
    out: dict[str, int] = {}
    for rows in by_area.values():
        rows.sort(key=lambda r: (status[r.id] != "active", -score_of[r.id]))
        for i, r in enumerate(rows):
            out[r.id] = i + 1
    return out


def _decide(c: ReviewedCapability, facts: ReviewFacts, cfg: RegistryConfig,
            now: datetime) -> tuple[str, JournalEntry] | None:  # fmt: skip
    src = facts.sources.get(c.domain)
    access = src.access if src else "unknown"
    mv = transition(CapState(c.status, c.attempts, c.acc_lb, c.yield_, c.status_since, access, c.recent,
                             c.signals_w), cfg.lifecycle, now)  # fmt: skip
    if mv is None or mv.to == c.status:
        return None
    rev = facts.reverts.get(c.id)
    fresh = rev is None or (c.last_used is not None and c.last_used > rev)
    verdict = limits.check(limits.Guard(c.domain, access, bool(src and src.frozen), c.status, rev, fresh), mv.to,
                           facts.deny)  # fmt: skip
    change = CHANGE_OF_MOVE.get(mv.to) or ("promoted" if mv.to == "candidate" and c.status == "discovered"
                                           else "reordered")  # fmt: skip
    evidence = {"acc_lb": c.acc_lb, "yield": c.yield_, "attempts": round(c.attempts, 2),
                "signals_w": round(c.signals_w, 2), "area": c.area, "market": c.market}  # fmt: skip
    return verdict, JournalEntry(c.domain, change, mv.reason, c.id, {"status": c.status}, {"status": mv.to},
                                 evidence, held=verdict == "held")  # fmt: skip


def _reorders(caps: Sequence[ReviewedCapability], moved: Mapping[str, str]) -> list[JournalEntry]:
    before = ranks(caps, {c.id: c.status for c in caps}, {c.id: c.score_before for c in caps})
    after = ranks(caps, {c.id: moved.get(c.id, c.status) for c in caps}, {c.id: c.score for c in caps})
    out = []
    for c in caps:
        b, a = before.get(c.id), after.get(c.id)
        if b and a and b != a and min(a, b) <= TOP_RANKS and abs(a - b) >= MIN_RANK_SHIFT:
            out.append(JournalEntry(
                c.domain, "reordered", f"{c.area}/{c.market}: moved from #{b} to #{a} by score {c.score:.3f}", c.id,
                {"rank": b}, {"rank": a}, {"score": c.score, "acc_lb": c.acc_lb, "yield": c.yield_},
            ))  # fmt: skip
    return out
