"""A relevance keyword change measured on stored pages (spec 011 US5 gap "manuales", research R14), the pure part:
which keyword lists are before and after, which words moved, the reference a value is checked against (gold, else
≥ 2 other families agreeing), and the measure built from the re-judged pages (`domain/relevance_audit` decides)."""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from automind.acquisition.domain import gates
from automind.acquisition.domain import relevance_audit as ra
from automind.acquisition.domain import replay as scoring
from automind.acquisition.domain.gates import AFTER_ACCEPTANCE, ObjectKind
from automind.acquisition.domain.tolerance import Tolerance, ToleranceKind, within
from automind.acquisition.gates.domain.change import Change

PREFIX = "relevance.keywords."
DEFAULT_TOL: Tolerance = (ToleranceKind.REL, 0.03)
KeywordLists = dict[str, list[str]]


def applies(c: Change) -> bool:
    """A change of the relevance keyword lists."""
    return c.object_kind == ObjectKind.RULE and c.object_key.startswith(PREFIX)


def keyword_sets(c: Change, current: Mapping[str, Sequence[str]]) -> tuple[KeywordLists, KeywordLists]:
    """(keyword lists before, after); a live change (watch, kept) has its old words as "before"."""
    name = c.object_key.removeprefix(PREFIX)
    now = {k: list(v) for k, v in current.items()}
    before = dict(now)
    if c.status in AFTER_ACCEPTANCE:
        before[name] = list(c.diff.get("from") or [])
    return before, {**now, name: [str(w) for w in (c.diff.get("to") or [])]}


def changed_words(c: Change) -> list[str]:
    """The words added or removed (a page can only move when it names one)."""
    old = {str(w).lower() for w in c.diff.get("from") or []}
    new = {str(w).lower() for w in c.diff.get("to") or []}
    return sorted(old ^ new)


def agreement(variant_id: str, attribute: str, rows: Sequence[tuple[float, str]], tol: Tolerance,
              min_families: int = 2) -> scoring.Gold | None:  # fmt: skip
    """The value ≥ `min_families` independent families agree on (within tolerance), as a gold; rows are
    (value, family)."""
    kind, t = tol
    best: tuple[int, float] | None = None
    for x, _ in rows:
        near = [(y, f) for y, f in rows if within(y, x, tol)]
        fams = len({f for _, f in near})
        if fams >= min_families and (best is None or fams > best[0]):
            best = (fams, statistics.median(y for y, _ in near))
    if best is None:
        return None
    return scoring.Gold(variant_id, attribute, best[1], None, "", t, kind, "agreement", None)


@dataclass
class References:
    """What a page's values are checked against: gold, else the accepted claims of other families."""

    gold: dict[tuple[str, str], scoring.Gold]
    claims: dict[tuple[str, str], list[tuple[float, str, str]]]  # (variant, attribute) -> (value, domain, family)
    tolerances: dict[str, Tolerance]
    min_families: int = 2

    def of(self, variant_id: str, attribute: str, domain: str) -> scoring.Gold | None:
        """The reference of a value read on `domain` (its own claims never count)."""
        g = self.gold.get((variant_id, attribute))
        if g is not None:
            return g
        rows = [(x, f) for x, d, f in self.claims.get((variant_id, attribute), []) if d != domain]
        return agreement(variant_id, attribute, rows, self.tolerances.get(attribute, DEFAULT_TOL), self.min_families)

    def check(self, values: Sequence[scoring.Value], domain: str) -> tuple[int, int]:
        """(right, wrong) of the values that have a reference."""
        right = wrong = 0
        for v in values:
            g = self.of(v.variant_id, v.attribute, domain)
            if g is None:
                continue
            if scoring.agrees(v, g, self.tolerances):
                right += 1
            else:
                wrong += 1
        return right, wrong


@dataclass(frozen=True)
class Rejudged:
    """A page whose stored verdict the old keywords reproduce, with the verdict the new ones give."""

    snapshot_id: str
    variant_id: str
    domain: str
    old: str
    new: str


@dataclass
class RelevanceResult:
    """The measure, as metrics for the journal, and the pages it covers (pinned while the gates run)."""

    measure: ra.RelevanceMeasure
    old: gates.Metrics
    new: gates.Metrics
    snapshot_ids: list[str]


def needs_values(p: Rejudged) -> bool:
    """Values are read only where the measure needs them: pages rejected before or newly rejected."""
    return p.old in ra.REJECTED or p.new in ra.REJECTED


def relevance_result(pages: Sequence[Rejudged], values: Mapping[tuple[str, str], list[scoring.Value]],
                     refs: References, unreproduced: int) -> RelevanceResult:  # fmt: skip
    """The measure of the re-judged pages: flips, the precision of their values, the junk of correct rejections."""
    checks: list[ra.PageCheck] = []
    old_vals: list[scoring.Value] = []
    new_vals: list[scoring.Value] = []
    for p in pages:
        vals = values.get((p.snapshot_id, p.variant_id), [])
        right, wrong = refs.check(vals, p.domain)
        chk = ra.PageCheck(p.snapshot_id, p.variant_id, p.old, p.new, right, wrong, len(vals))
        checks.append(chk)
        if chk.flipped:
            new_vals += vals
        elif chk.lost:
            old_vals += vals
    m = ra.RelevanceMeasure.from_pages(checks, unreproduced)
    lost = [c for c in checks if c.lost]
    n = len(checks)
    old_m = gates.Metrics(pages=n, yield_=len(old_vals) / n if n else 0.0,
                          gold_covered=sum(x.right + x.wrong for x in lost), gold_match=sum(x.right for x in lost),
                          accuracy_lb=scoring.wilson_lb(sum(x.right for x in lost),
                                                        sum(x.right + x.wrong for x in lost)))  # fmt: skip
    new_m = gates.Metrics(pages=n, yield_=len(new_vals) / n if n else 0.0, gold_covered=m.values_checked,
                          gold_match=m.values_right, accuracy_lb=m.precision_lb)  # fmt: skip
    return RelevanceResult(m, old_m, new_m, sorted({p.snapshot_id for p in pages}))
