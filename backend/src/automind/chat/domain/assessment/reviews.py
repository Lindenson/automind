"""Review summaries: recurring vs isolated points and the review minimum (FR-037, FR-019). Pure."""

from __future__ import annotations

from dataclasses import dataclass

from automind.chat.domain.assessment.metrics import ReviewSummary

MIN_REVIEWS = 5
MIN_SOURCES = 2


@dataclass(frozen=True)
class ReviewIn:
    tag: str
    polarity: str  # PRO | CON
    text: str
    domain: str
    reviewer: str = "EXPERT"
    evidence_id: str = ""


def summarize_reviews(items: list[ReviewIn]) -> ReviewSummary:
    """Recurring = the same tag and polarity from ≥2 source domains; the rest are isolated opinions."""
    groups: dict[tuple[str, str], list[ReviewIn]] = {}
    for r in items:
        groups.setdefault((r.tag, r.polarity), []).append(r)
    rec: dict[str, tuple[int, int]] = {}
    iso: dict[str, tuple[int, int]] = {}
    for (tag, pol), rs in groups.items():
        target = rec if len({r.domain for r in rs}) >= MIN_SOURCES else iso
        pro, con = target.get(tag, (0, 0))
        target[tag] = (pro + len(rs), con) if pol == "PRO" else (pro, con + len(rs))
    sources = len({r.domain for r in items})
    return ReviewSummary(
        minimum_met=len(items) >= MIN_REVIEWS and sources >= MIN_SOURCES,
        recurring=rec,
        isolated=iso,
        review_count=len(items),
        source_count=sources,
    )
