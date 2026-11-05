"""Replay comparison against gold and the replay report (spec 011 FR-004, research R4). Pure.

A replay reads stored pages with a reader version, validates the rows with the live rules, and compares each
accepted value with the gold value of the page's variant(s). The report has the fields of contracts/replay-cli.md.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

Tolerance = tuple[str, float]
Z = 1.96


@dataclass(frozen=True)
class Value:
    """An accepted value read from one stored page (canonical units)."""

    snapshot_id: str
    url: str
    variant_id: str
    attribute: str
    num: float | None
    text: str | None
    unit: str | None
    quote: str


@dataclass(frozen=True)
class Gold:
    variant_id: str
    attribute: str
    num: float | None
    text: str | None
    unit: str
    tolerance: float | None
    tolerance_kind: str | None
    rule: str
    dataset: str | None


@dataclass(frozen=True)
class PageResult:
    snapshot_id: str
    url: str
    variant_ids: tuple[str, ...]
    rows_read: int
    values: list[Value]  # accepted values only (yield, pass rate)
    # what accuracy is scored on: for a reader, every row it read (unit layer only, the raw text when even that
    # fails), so a reader that puts the wrong number under a label is wrong even when the checks catch it
    scored: list[Value] | None = None


@dataclass(frozen=True)
class Mismatch:
    snapshot_id: str
    url: str
    variant_id: str
    attribute: str
    ours: float | str | None
    gold: float | str | None
    unit: str
    gold_rule: str
    gold_dataset: str | None
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Comparison:
    by_attribute: dict[str, dict[str, int]] = field(default_factory=dict)
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def covered(self) -> int:
        return sum(a["covered"] for a in self.by_attribute.values())

    @property
    def matched(self) -> int:
        return sum(a["match"] for a in self.by_attribute.values())


def norm_text(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def agrees(ours: Value, g: Gold, tolerances: dict[str, Tolerance]) -> bool:
    if g.num is None:
        return g.text is not None and norm_text(ours.text) == norm_text(g.text)
    if ours.num is None:
        return False
    kind, tol = (
        (g.tolerance_kind, g.tolerance)
        if g.tolerance is not None and g.tolerance_kind
        else tolerances.get(g.attribute, ("rel", 0.0))
    )
    return abs(ours.num - g.num) <= (tol if kind == "abs" else tol * abs(g.num)) + 1e-9


def compare(values: list[Value], gold: dict[tuple[str, str], Gold], tolerances: dict[str, Tolerance]) -> Comparison:
    """Count, per attribute, values that have gold (covered) and those within tolerance (match)."""
    c = Comparison()
    for v in values:
        g = gold.get((v.variant_id, v.attribute))
        if g is None:
            continue
        slot = c.by_attribute.setdefault(v.attribute, {"covered": 0, "match": 0})
        slot["covered"] += 1
        if agrees(v, g, tolerances):
            slot["match"] += 1
        else:
            c.mismatches.append(
                Mismatch(
                    v.snapshot_id,
                    v.url,
                    v.variant_id,
                    v.attribute,
                    v.num if v.num is not None else v.text,
                    g.num if g.num is not None else g.text,
                    g.unit,
                    g.rule,
                    g.dataset,
                    v.quote,
                )  # fmt: skip
            )
    c.mismatches.sort(key=lambda m: (m.attribute, m.url, m.snapshot_id))
    return c


def wilson_lb(k: int, n: int, z: float = Z) -> float | None:
    """Wilson score lower bound of k successes in n trials; None without trials."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def report(
    version: str,
    pages: list[PageResult],
    gold: dict[tuple[str, str], Gold],
    tolerances: dict[str, Tolerance],
    period: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """The replay report (contracts/replay-cli.md), without timing and call counts (the runner adds them)."""
    n = len(pages)
    rows_read = sum(p.rows_read for p in pages)
    values = [v for p in pages for v in p.values]
    c = compare([v for p in pages for v in (p.values if p.scored is None else p.scored)], gold, tolerances)
    covered, matched = c.covered, c.matched
    return {
        "version": version,
        "period": {"from": period[0], "to": period[1]} if period else None,
        "pages": n,
        "pages_with_fields": sum(1 for p in pages if p.rows_read > 0),
        "fields_per_page": rows_read / n if n else 0.0,
        "yield": len(values) / n if n else 0.0,
        "rows_read": rows_read,
        "rows_accepted": len(values),
        "pass_rate": len(values) / rows_read if rows_read else 0.0,
        "gold_covered": covered,
        "gold_match": matched,
        "accuracy": matched / covered if covered else None,
        "accuracy_lb": wilson_lb(matched, covered),
        "by_attribute": dict(sorted(c.by_attribute.items())),
        "mismatches": [m.as_dict() for m in c.mismatches],
    }
