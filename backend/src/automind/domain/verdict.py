"""The verdict, built by code (spec 004 FR-001, FR-011; research R2). Pure.

Inputs: the criteria ranking (on the criteria every car has, with the tie margin), the insights and what data
is missing. Output: the pick or a tie, 2–3 reasons (insight ids), the main trade-off, a confidence with its
reason and what would change the verdict. The model only phrases the headline; it never chooses the pick.

Confidence:
- HIGH: the ranking covers ≥ 80% of the user's weights and every decisive insight is well sourced;
- MEDIUM: ≥ 60% of the weights;
- LOW: otherwise. Key data missing for a car lowers it by one step.
No ranking basis at all gives "not enough data to recommend".

Limits (spec 007 FR-017). A car whose price is over the budget, or whose running cost per month is over the
user's limit, cannot be the plain pick:
- the best in-limit car becomes the pick when its total is at least the top total − 2 × TIE_MARGIN; the top car
  is then named "best if the budget allows";
- otherwise the top car stays, headed "best if the budget allows", and the limit finding is shown with numbers.
A tie where only some of the tied cars are over a limit resolves to the in-limit one by the same rule. When every
car is over a limit, the ranking stands and only the limit findings are shown.

Another profile (spec 007 FR-018): when the same data scored with another persona's weights has a different
clear winner, the verdict carries it (`other_profile`) so the text can say so. Code computes it; the model only
phrases it.

Used cars without used prices or wear data (FR-019) lower the confidence by one step and are listed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from .criteria import TIE_MARGIN, CarScore, CriteriaScore
from .insights import Insight, InsightSet, TradeOff

Confidence = Literal["HIGH", "MEDIUM", "LOW"]
_DOWN: dict[str, Confidence] = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}
MAX_REASONS = 3
HIGH_SHARE, MEDIUM_SHARE, MIN_SHARE = 0.8, 0.6, 0.3


@dataclass(frozen=True)
class WouldChange:
    kind: Literal["BREAK_EVEN", "PRIORITY", "DATA"]
    car_id: str | None  # the car that would win instead
    insight_id: str | None = None
    years: float | None = None  # BREAK_EVEN: keep the car longer than this
    gaps: tuple[str, ...] = ()  # DATA: what is missing


@dataclass(frozen=True)
class Limit:
    car_id: str
    kind: Literal["OVER_BUDGET", "OVER_MONTHLY"]
    value_eur: float  # price, or running cost per month
    limit_eur: float


@dataclass(frozen=True)
class OtherProfile:
    persona: str
    car_id: str


@dataclass(frozen=True)
class UsedMissing:
    car_id: str
    missing: tuple[str, ...]  # price_used, wear


@dataclass(frozen=True)
class Verdict:
    pick_car_id: str | None
    tie: bool
    reasons: tuple[str, ...]  # insight ids, most relevant first
    trade_off: TradeOff | None
    confidence: Confidence
    confidence_reason: Literal["COVERAGE_HIGH", "COVERAGE_MEDIUM", "COVERAGE_LOW", "GAPS", "NO_DATA", "SINGLE"]
    would_change: WouldChange | None
    tied_cars: tuple[str, ...] = ()
    not_enough_data: bool = False
    different_needs: bool = False  # e.g. a city car against a large 4x4
    gaps: tuple[str, ...] = field(default_factory=tuple)  # "car label: area" of the key data that is missing
    coverage: float = 0.0  # share of the user's weights the ranking is based on
    limits: tuple[Limit, ...] = ()
    best_if_budget: str | None = None  # the top-scored car that is over a limit
    other_profile: OtherProfile | None = None
    used_missing: tuple[UsedMissing, ...] = ()


def _share(score: CriteriaScore) -> float:
    total = sum(w for w in score.weights.values() if w > 0)
    if total <= 0:
        return 0.0
    return round(sum(score.weights.get(c, 0.0) for c in score.common) / total, 3)


def _confidence(share: float, decisive: Sequence[Insight], gaps: Sequence[str]) -> tuple[Confidence, str]:
    level: Confidence
    if share >= HIGH_SHARE and decisive and all(i.confidence == "HIGH" for i in decisive):
        level, why = "HIGH", "COVERAGE_HIGH"
    elif share >= MEDIUM_SHARE:
        level, why = "MEDIUM", "COVERAGE_MEDIUM"
    else:
        level, why = "LOW", "COVERAGE_LOW"
    if gaps:
        return _DOWN[level], "GAPS"
    return level, why


MAX_BREAK_EVEN_YEARS = 15.0  # beyond this a payback is no payback ("after 77 years", incident 2026-11-03)


def _would_change(pick: str | None, s: InsightSet, trade: TradeOff | None) -> WouldChange | None:
    if (trade is not None and trade.break_even_years and trade.break_even_years <= MAX_BREAK_EVEN_YEARS
            and pick in (trade.gain_car, trade.cost_car)):  # fmt: skip
        other = trade.cost_car if pick == trade.gain_car else trade.gain_car
        return WouldChange("BREAK_EVEN", other, trade.gain, years=trade.break_even_years)
    rival = next((i for i in s.meaningful() if i.better_car and i.better_car != pick), None)
    if rival is not None:
        return WouldChange("PRIORITY", rival.better_car, rival.id)
    return None


def _not_enough(s: InsightSet, gaps: tuple[str, ...], share: float, why: str) -> Verdict:
    """No ranking: no pick, but the clear differences that are known are still shown as reasons."""
    wc = WouldChange("DATA", None, gaps=gaps) if gaps else None
    reasons = tuple(i.id for i in s.meaningful()[:MAX_REASONS])
    return Verdict(None, False, reasons, None, "LOW", why, wc, not_enough_data=True, gaps=gaps,  # type: ignore[arg-type]
                   coverage=share)  # fmt: skip


def build(
    score: CriteriaScore | None,
    s: InsightSet,
    *,
    gaps: Sequence[str] = (),
    different_needs: bool = False,
    limits: Sequence[Limit] = (),
    other_profile: OtherProfile | None = None,
    used_missing: Sequence[UsedMissing] = (),
) -> Verdict:
    v = _build(score, s, tuple(gaps), different_needs, tuple(limits), tuple(used_missing))
    keep = other_profile if other_profile is not None and other_profile.car_id != v.pick_car_id else None
    return replace(v, limits=tuple(limits), other_profile=keep if v.pick_car_id or v.tie else None,
                   used_missing=tuple(used_missing))  # fmt: skip


def _limit_pick(ranked: Sequence[CarScore], tie: bool, pick: str | None, over: set[str]) -> tuple[str | None, bool,
                                                                                               str | None]:  # fmt: skip
    """The documented limits rule (module docstring): (pick, tie, best_if_budget)."""
    top = ranked[0]
    if not over or all(c.car_id in over for c in ranked):  # none fits: the scores decide, the notes say so
        return pick, tie, None
    if top.car_id not in over and not (tie and ranked[1].car_id in over):
        return pick, tie, None
    if top.car_id not in over:  # a tie with an over-limit runner-up: the in-limit car
        return top.car_id, False, ranked[1].car_id
    runner = next((c for c in ranked if c.car_id not in over), None)
    if runner is not None and (runner.total or 0) >= (top.total or 0) - 2 * TIE_MARGIN:
        return runner.car_id, False, top.car_id
    return top.car_id, False, top.car_id


def _build(
    score: CriteriaScore | None, s: InsightSet, gaps_t: tuple[str, ...], different_needs: bool,
    limits: tuple[Limit, ...], used_missing: tuple[UsedMissing, ...],
) -> Verdict:  # fmt: skip
    if s.single:
        return Verdict(None, False, (), None, "MEDIUM" if not gaps_t else "LOW", "SINGLE", None, gaps=gaps_t)
    share = _share(score) if score is not None else 0.0
    if score is None or not score.common or share < MIN_SHARE:
        return _not_enough(s, gaps_t, share, "NO_DATA" if score is None or not score.common else "COVERAGE_LOW")
    ranked = sorted(
        (c for c in score.cars if c.ranked and c.total is not None), key=lambda c: (-(c.total or 0), c.car_id)
    )
    if len(ranked) < 2:  # too little data for a ranking: no pick and no "tie" between unranked cars
        return _not_enough(s, gaps_t, share, "COVERAGE_LOW")
    tie = score.tie or score.winner_car_id is None
    pick = None if tie else score.winner_car_id
    pick, tie, best_if = _limit_pick(ranked, tie, pick, {x.car_id for x in limits})
    tied = tuple(c.car_id for c in ranked[:2]) if tie else ()
    meaningful = s.meaningful()
    if pick is not None:
        reasons = [i for i in meaningful if i.better_car == pick][:MAX_REASONS]
    else:  # a tie: the differences that would tip it for this user
        reasons = [i for i in meaningful if i.better_car in tied][:MAX_REASONS]
    trade = next((t for t in s.trade_offs if pick in (t.gain_car, t.cost_car) or pick is None), None)
    conf, why = _confidence(share, reasons, gaps_t)
    if used_missing and why != "GAPS":
        conf, why = _DOWN[conf], "GAPS"
    wc = _would_change(pick, s, trade) if pick else (
        WouldChange("PRIORITY", reasons[0].better_car, reasons[0].id) if reasons else None)  # fmt: skip
    if gaps_t and wc is None:
        wc = WouldChange("DATA", None, gaps=gaps_t)
    return Verdict(
        pick_car_id=pick, tie=tie, reasons=tuple(i.id for i in reasons), trade_off=trade, confidence=conf,
        confidence_reason=why,  # type: ignore[arg-type]
        would_change=wc, tied_cars=tied, different_needs=different_needs, gaps=gaps_t, coverage=share,
        best_if_budget=best_if,
    )  # fmt: skip


CLASS_ORDER = ("small", "compact", "mid_large", "premium_suv_4x4")


def very_different(classes: Sequence[str | None]) -> bool:
    """Cars two or more size classes apart serve different needs (a city car against a large 4x4)."""
    idx = [CLASS_ORDER.index(c) for c in classes if c in CLASS_ORDER]
    return len(idx) >= 2 and max(idx) - min(idx) >= 2
