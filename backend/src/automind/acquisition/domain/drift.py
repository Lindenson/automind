"""Parser drift detection (spec 011 US4, research R12, FR-016). Pure.

Three detectors for three failure shapes, over the daily metrics of one parser version:
- slow decay: fields per page over the last 7 days below (1 − `yield_drop`) × the 30-day baseline before them;
- worse checks: pass rate over the last 7 days below the baseline's minus `pass_drop`;
- redesign: the latest day's structure similarity to the 30-day reference below `min_similarity`, even before the
  yield drops;
each only with at least `min_pages_7d` pages in the last 7 days. And at once, outside the daily task: `zero_streak`
pages in a row with no field.
The baseline is the 30 days before the 7-day window, so a drop is not diluted by itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

ORDER = ("structure", "yield_drop", "pass_drop")  # the first found names the verdict; the reason lists all


@dataclass(frozen=True)
class DriftConfig:
    min_pages_7d: int = 15
    yield_drop: float = 0.3
    pass_drop: float = 0.15
    min_similarity: float = 0.6
    zero_streak: int = 5

    @classmethod
    def from_mapping(cls, m: Mapping[str, Any] | None) -> DriftConfig:
        m = m or {}
        d = cls()
        return cls(
            min_pages_7d=int(m.get("min_pages_7d", d.min_pages_7d)),
            yield_drop=float(m.get("yield_drop", d.yield_drop)),
            pass_drop=float(m.get("pass_drop", d.pass_drop)),
            min_similarity=float(m.get("min_similarity", d.min_similarity)),
            zero_streak=int(m.get("zero_streak", d.zero_streak)),
        )


@dataclass(frozen=True)
class DayStat:
    day: date
    pages: int
    fields_total: int
    rows_read: int = 0
    rows_accepted: int = 0
    zero_pages: int = 0
    structure_sim: float | None = None


@dataclass(frozen=True)
class Window:
    pages: int
    fields_per_page: float | None
    pass_rate: float | None


@dataclass(frozen=True)
class Drift:
    kind: str  # structure | yield_drop | pass_drop | zero_streak
    reason: str  # one line with the numbers, shown to the owner and journalled
    signals: dict[str, dict[str, float]] = field(default_factory=dict)


def window(days: Sequence[DayStat]) -> Window:
    pages = sum(d.pages for d in days)
    read = sum(d.rows_read for d in days)
    return Window(
        pages=pages,
        fields_per_page=(sum(d.fields_total for d in days) / pages) if pages else None,
        pass_rate=(sum(d.rows_accepted for d in days) / read) if read else None,
    )


def windows(days: Sequence[DayStat], today: date) -> tuple[Window, Window, DayStat | None]:
    """(last 7 days, the 30 days before them, the latest day with pages)."""
    recent = [d for d in days if today - timedelta(days=6) <= d.day <= today]
    base = [d for d in days if today - timedelta(days=36) <= d.day <= today - timedelta(days=7)]
    latest = max((d for d in recent if d.pages), key=lambda d: d.day, default=None)
    return window(recent), window(base), latest


def verdict(days: Sequence[DayStat], today: date, cfg: DriftConfig) -> Drift | None:
    """The drift of a parser version on `today`, or None (no drift, or too few pages to say)."""
    w7, w30, latest = windows(days, today)
    if w7.pages < cfg.min_pages_7d:
        return None
    found: dict[str, tuple[str, dict[str, float]]] = {}
    sim = latest.structure_sim if latest is not None else None
    if sim is not None and sim < cfg.min_similarity:
        found["structure"] = (f"structure changed (similarity {sim:.2f} < {cfg.min_similarity:.2f} on {latest.day})",
                              {"similarity": round(sim, 3)})  # fmt: skip
    f7, f30 = w7.fields_per_page, w30.fields_per_page
    if f7 is not None and f30 and f7 < (1 - cfg.yield_drop) * f30:
        found["yield_drop"] = (
            f"fields per page {f7:.1f} vs {f30:.1f} (−{(1 - f7 / f30) * 100:.0f} %, {w7.pages} pages in 7 days)",
            {"fields_per_page_7d": round(f7, 2), "fields_per_page_30d": round(f30, 2), "pages_7d": float(w7.pages)},
        )
    p7, p30 = w7.pass_rate, w30.pass_rate
    if p7 is not None and p30 is not None and p7 < p30 - cfg.pass_drop:
        found["pass_drop"] = (f"pass rate {p7:.2f} vs {p30:.2f}", {"pass_rate_7d": round(p7, 3),
                                                                     "pass_rate_30d": round(p30, 3)})  # fmt: skip
    if not found:
        return None
    kind = next(k for k in ORDER if k in found)
    reason = "; ".join(found[k][0] for k in ORDER if k in found)
    if "yield_drop" not in found and f7 is not None and f30:
        reason += f"; fields per page {f7:.1f} vs {f30:.1f}"  # the yield, for context
    return Drift(kind, reason, {k: v[1] for k, v in found.items()})


def zero_streak(streak: int, cfg: DriftConfig) -> Drift | None:
    """A sudden break: `cfg.zero_streak` pages in a row with no field → degraded at once."""
    if streak < cfg.zero_streak:
        return None
    return Drift("zero_streak", f"{streak} pages in a row with no fields", {"zero_streak": {"pages": float(streak)}})
