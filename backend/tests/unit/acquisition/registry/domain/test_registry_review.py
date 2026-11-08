"""Spec 012 A4a: the decisions of the daily review are pure — refused moves, held moves and the re-order journal."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.records import ReviewedCapability, SourceState
from automind.acquisition.registry.domain.review import ReviewFacts, plan_review

NOW = datetime(2026, 11, 8, tzinfo=UTC)


def cap(cid: str, status: str, score: float, before: float, recent: tuple[bool, ...] = (True,) * 10,
        acc_lb: float = 0.5, yield_: float = 0.5) -> ReviewedCapability:  # fmt: skip
    return ReviewedCapability(id=cid, domain=f"{cid}.es", area="specs", market="ES", status=status,
                              status_since=NOW - timedelta(days=1), attempts=20, acc_lb=acc_lb, yield_=yield_,
                              score=score, score_before=before, recent=recent)  # fmt: skip


def test_a_deny_listed_source_is_never_promoted_and_counts_as_refused() -> None:
    c = replace(cap("deny", "candidate", 0.5, 0.5, acc_lb=0.9, yield_=0.9), signals_w=10)
    plan = plan_review([c], ReviewFacts({"deny.es": SourceState("ok")}, deny=("deny.es",)), RegistryConfig(), NOW)
    assert plan.moves == () and plan.journal == () and plan.stats["refused"] == 1


def test_a_shift_of_two_ranks_in_the_top_ten_is_journalled() -> None:
    caps = [cap("a", "active", 0.1, 0.9), cap("b", "active", 0.5, 0.5), cap("c", "active", 0.9, 0.1)]
    plan = plan_review(caps, ReviewFacts({f"{x}.es": SourceState("ok") for x in "abc"}), RegistryConfig(), NOW)
    assert plan.moves == () and plan.stats["reordered"] == 2
    assert [(e.domain, e.before, e.after) for e in plan.journal] == [
        ("a.es", {"rank": 1}, {"rank": 3}), ("c.es", {"rank": 3}, {"rank": 1})
    ]  # fmt: skip
