"""Deterministic insights: the meaningful differences between the compared cars (spec 004 FR-003, FR-009,
FR-013; research R1). Pure.

Before any text is written, code decides which differences matter:

- per attribute, cars are grouped into tiers: values closer than the attribute's threshold are "about the
  same" (583 L vs 580 L of boot is a tie, never a win);
- an insight is *meaningful* when the cars fall into more than one tier; it names a winner (`better_car`) only
  when the best tier holds a single car;
- relevance = the weight of the user's criterion behind the attribute × how far the difference exceeds the
  threshold (capped), so the user's priorities come first;
- money: a consumption difference is also expressed in € per year at the user's km;
- ownership cost is compared on the TOTAL over the user's period, running costs plus the value the car loses
  (`tco_period`); running costs per year (`tco_per_year`) are a secondary figure, labelled "without
  depreciation" (chat 5821ac77: a verdict on running costs alone called the dearer car the saving);
- trade-offs: one car cheaper to buy, the other cheaper to run give a payback in years, from the cars' total cost
  curves (running + value lost, year by year), never from running costs alone. When the cheaper-to-run car is
  still dearer over the period, the trade-off says so (`no_payback`, or a payback beyond the period).

The same input always gives the same output (sorted, no randomness).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from automind.chat.domain.cost.tco import payback_years

Direction = Literal["higher", "lower"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]
_CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
MAX_MAGNITUDE = 3.0


@dataclass(frozen=True)
class AttributeRule:
    key: str
    label: str
    unit: str
    direction: Direction
    criterion: str | None = None
    threshold_abs: float | None = None
    threshold_rel: float | None = None
    money: str | None = None

    @classmethod
    def from_config(cls, key: str, d: Mapping[str, Any]) -> AttributeRule:
        return cls(
            key=key, label=str(d.get("label", key)), unit=str(d.get("unit", "")),
            direction="lower" if d.get("direction") == "lower" else "higher", criterion=d.get("criterion"),
            threshold_abs=float(d["threshold_abs"]) if d.get("threshold_abs") is not None else None,
            threshold_rel=float(d["threshold_rel"]) if d.get("threshold_rel") is not None else None,
            money=d.get("money"),
        )  # fmt: skip

    def threshold(self, reference: float) -> float:
        """The smallest difference that counts, for values around `reference` (abs or rel, whichever is smaller
        when both are given: either one is enough to call it meaningful)."""
        options = []
        if self.threshold_abs is not None:
            options.append(self.threshold_abs)
        if self.threshold_rel is not None:
            options.append(abs(reference) * self.threshold_rel)
        return min(options) if options else 0.0


def rules_from_config(d: Mapping[str, Any]) -> dict[str, AttributeRule]:
    return {k: AttributeRule.from_config(k, v) for k, v in (d.get("attributes") or {}).items()}


@dataclass(frozen=True)
class CarValues:
    """Validated values of one car for the insight attributes (canonical units)."""

    car_id: str
    label: str
    values: Mapping[str, float]
    confidence: Mapping[str, str] = field(default_factory=dict)  # attribute -> HIGH | MEDIUM | LOW
    sources: Mapping[str, Sequence[str]] = field(default_factory=dict)  # attribute -> claim/evidence ids
    energy_eur_per_unit: float | None = None  # € per litre / kWh of this car's energy (for money per year)
    cost_curve: tuple[float, ...] = ()  # total cost incl. value lost after 1, 2, … years (empty: value loss unknown)


@dataclass(frozen=True)
class Profile:
    weights: Mapping[str, float]  # criterion -> weight (any scale)
    annual_km: int = 15000
    background_weight: float = 0.3
    years: int = 5  # the ownership period the totals cover


@dataclass(frozen=True)
class CarValue:
    car_id: str
    value: float


@dataclass(frozen=True)
class Insight:
    id: str
    attribute: str
    label: str
    unit: str
    cars: tuple[CarValue, ...]  # best first
    tiers: tuple[tuple[str, ...], ...]  # car ids grouped "about the same", best tier first
    diff: float  # best vs the next tier (or vs the others when one tier): absolute, in the unit
    rel_diff: float
    threshold: float
    meaningful: bool
    better_car: str | None  # the single car of the best tier when meaningful
    worse_car: str | None
    relevance: float
    confidence: Confidence
    criterion: str | None
    money_per_year: float | None = None  # € per year at the user's km (consumption)
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class TradeOff:
    gain: str  # insight id won by `gain_car`
    cost: str  # insight id won by the other car
    gain_car: str
    cost_car: str
    break_even_years: float | None  # when gain_car's total cost (running + value lost) drops to cost_car's
    no_payback: bool = False  # gain_car is cheaper to run but its total never drops to cost_car's (≤ 15 years)
    period_loser: str | None = None  # the car whose total over the period is higher, when the totals are known


@dataclass(frozen=True)
class InsightSet:
    insights: tuple[Insight, ...]  # meaningful first, then by relevance
    ties: tuple[str, ...]  # insight ids whose cars are all about the same
    trade_offs: tuple[TradeOff, ...] = ()
    single: bool = False  # one car: no comparison

    def meaningful(self) -> list[Insight]:
        return [i for i in self.insights if i.meaningful]

    def get(self, insight_id: str) -> Insight | None:
        return next((i for i in self.insights if i.id == insight_id), None)


def _tiers(vals: list[CarValue], rule: AttributeRule) -> list[list[CarValue]]:
    """Group sorted values: a new tier starts when the gap to the tier's best value reaches the threshold."""
    tiers: list[list[CarValue]] = []
    for cv in vals:
        if tiers and abs(tiers[-1][0].value - cv.value) < rule.threshold(tiers[-1][0].value):
            tiers[-1].append(cv)
        else:
            tiers.append([cv])
    return tiers


def _min_conf(cars: Sequence[CarValues], attr: str) -> Confidence:
    levels = [str(c.confidence.get(attr, "MEDIUM")) for c in cars]
    worst = min(levels, key=lambda x: _CONF_ORDER.get(x, 1))
    return worst if worst in _CONF_ORDER else "MEDIUM"  # type: ignore[return-value]


def _weight(rule: AttributeRule, profile: Profile) -> float:
    total = sum(w for w in profile.weights.values() if w > 0) or 1.0
    w = profile.weights.get(rule.criterion or "", 0.0) / total
    return max(w, profile.background_weight / max(len(profile.weights), 1))


def _money(rule: AttributeRule, best: CarValues, worst: CarValues, profile: Profile) -> float | None:
    if rule.money != "per_year_at_km":
        return None
    a, b = best.values.get(rule.key), worst.values.get(rule.key)
    pa, pb = best.energy_eur_per_unit, worst.energy_eur_per_unit
    if a is None or b is None or not pa or not pb:
        return None
    return round(abs(b * pb - a * pa) * profile.annual_km / 100, 0)


def _insight(rule: AttributeRule, cars: Sequence[CarValues], profile: Profile) -> Insight | None:
    have = [c for c in cars if rule.key in c.values]
    if len(have) < 2:
        return None
    rev = rule.direction == "higher"
    vals = sorted((CarValue(c.car_id, float(c.values[rule.key])) for c in have),
                  key=lambda x: (-x.value if rev else x.value, x.car_id))  # fmt: skip
    tiers = _tiers(vals, rule)
    best, nxt = tiers[0][0], (tiers[1][0] if len(tiers) > 1 else vals[-1])
    diff = round(abs(best.value - nxt.value), 3)
    ref = abs(nxt.value) or 1.0
    threshold = rule.threshold(best.value)
    meaningful = len(tiers) > 1  # some car is clearly better or worse; a shared lead has no single winner
    by_id = {c.car_id: c for c in have}
    worst = vals[-1]
    money = _money(rule, by_id[best.car_id], by_id[worst.car_id], profile) if meaningful else None
    magnitude = min(diff / threshold, MAX_MAGNITUDE) if threshold > 0 else (1.0 if diff else 0.0)
    relevance = round(_weight(rule, profile) * magnitude, 4) if meaningful else 0.0
    srcs = tuple(sorted({s for c in have for s in c.sources.get(rule.key, ())}))
    return Insight(
        id=rule.key, attribute=rule.key, label=rule.label, unit=rule.unit, cars=tuple(vals),
        tiers=tuple(tuple(x.car_id for x in t) for t in tiers), diff=diff, rel_diff=round(diff / ref, 4),
        threshold=round(threshold, 3), meaningful=meaningful,
        better_car=best.car_id if meaningful and len(tiers[0]) == 1 else None,
        worse_car=worst.car_id if meaningful and len(tiers[-1]) == 1 else None,
        relevance=relevance, confidence=_min_conf(have, rule.key), criterion=rule.criterion,
        money_per_year=money, sources=srcs,
    )  # fmt: skip


_PRICE = "official_price_es"
_PERIOD = "tco_period"
_RUNNING = ("tco_per_year", "consumption")


def _trade_offs(found: Sequence[Insight], cars: Sequence[CarValues] = ()) -> list[TradeOff]:
    """Opposite winners on meaningful insights. Price against running cost gives a payback, counted on the total
    cost curves (running + value lost); without them no payback is claimed."""
    by = {i.id: i for i in found if i.meaningful and i.better_car}
    curves = {c.car_id: c.cost_curve for c in cars if c.cost_curve}
    out: list[TradeOff] = []
    price = by.get(_PRICE)
    period = next((i for i in found if i.id == _PERIOD and i.meaningful), None)
    loser = period.worse_car if period is not None else None
    for run in (by.get(k) for k in _RUNNING):
        if price is None or run is None or run.better_car == price.better_car:
            continue
        gain, other = str(run.better_car), str(price.better_car)
        years, never = None, False
        if gain in curves and other in curves:
            years = payback_years(curves[gain], curves[other])
            never = years is None
        win_period = period is not None and period.better_car == gain
        out.append(TradeOff(_PERIOD if win_period else run.id, _PRICE if win_period or period is None else _PERIOD,
                            gain, other, years, never, loser))  # fmt: skip
        break
    ranked = sorted(by.values(), key=lambda i: (-i.relevance, i.id))
    for a in ranked:
        b = next((x for x in ranked if x.better_car not in (None, a.better_car)), None)
        if b is not None and not any({t.gain, t.cost} == {a.id, b.id} for t in out):
            out.append(TradeOff(a.id, b.id, str(a.better_car), str(b.better_car), None))
            break
    return out


def build(cars: Sequence[CarValues], profile: Profile, rules: Mapping[str, AttributeRule]) -> InsightSet:
    if len(cars) < 2:
        return InsightSet((), (), (), single=True)
    found = [i for i in (_insight(r, cars, profile) for _, r in sorted(rules.items())) if i is not None]
    found.sort(key=lambda i: (not i.meaningful, -i.relevance, i.id))
    ties = tuple(i.id for i in found if len(i.tiers) == 1)
    return InsightSet(tuple(found), ties, tuple(_trade_offs(found, cars)))
