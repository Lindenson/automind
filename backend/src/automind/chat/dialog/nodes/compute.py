"""compute: deterministic numbers and blocks for a report or an answer (FR-027..FR-032, R5).

Criteria scores, metrics, drag race and blocks come only from code (constitution III), ordered per
persona (FR-030). Weight changes recompute from cached data without research (FR-029, SC-009).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from automind.acquisition import api as acquisition
from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.report.blocks import car_view, electric
from automind.chat.application.services.report.blocks.case_summary import case_summary_block
from automind.chat.application.services.report.blocks.criteria import criteria_block
from automind.chat.application.services.report.blocks.data_panel import data_panel_block
from automind.chat.application.services.report.blocks.engineering import engineering_block
from automind.chat.application.services.report.blocks.manufacturer import manufacturer_block
from automind.chat.application.services.report.blocks.metric_bars import metric_bars
from automind.chat.application.services.report.blocks.race import race_block
from automind.chat.application.services.report.blocks.reliability import reliability_block
from automind.chat.application.services.report.blocks.reviews import reviews_block
from automind.chat.application.services.report.blocks.sources import sources_block
from automind.chat.application.services.report.blocks.spec_table import spec_table
from automind.chat.application.services.report.blocks.tco import evidence_refs, tco_block
from automind.chat.application.services.report.blocks.value_retention import value_retention_block
from automind.chat.application.services.report.facts.car import (
    load_car,
    new_price,
    short_name,
    used_price,
    warranty_years,
)
from automind.chat.application.services.report.facts.race import run_race
from automind.chat.application.services.report.facts.scoring_inputs import car_facts, insight_values
from automind.chat.application.services.report.tco_inputs import tco_car
from automind.chat.application.services.report.writer_facts import summary_for_llm
from automind.chat.dialog import report_text
from automind.chat.dialog.context import notice, record_intake
from automind.chat.dialog.guard import CheckInput as GuardInput
from automind.chat.dialog.phrases import energy_input, market_name, t
from automind.chat.dialog.runner import TurnContext
from automind.chat.domain import understanding
from automind.chat.domain.assessment.criteria import CriteriaScore, score, weight_breakdown, weights_for
from automind.chat.domain.assessment.metrics import new_generation_since
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import incentives, tco
from automind.chat.domain.cost.energy import UsageContext
from automind.chat.domain.identification import used
from automind.chat.domain.verdict import insights as ins
from automind.chat.domain.verdict import suggestions
from automind.chat.domain.verdict import verdict as vd
from automind.chat.domain.verdict.report_layout import annotate_sections, depths, order_blocks
from automind.shared.evidence import sense
from automind.shared.research_order import plan as research_plan
from automind.shared.vehicle import markets


@dataclass
class Computed:
    blocks: list[dict[str, Any]]
    facts: dict[str, Any]
    criteria: CriteriaScore | None
    cars: list[dict[str, Any]] = field(default_factory=list)
    tco: list[Any] = field(default_factory=list)
    race: Any = None
    insights: Any = None  # domain.insights.InsightSet (spec 004 US3)
    verdict: Any = None  # domain.verdict.Verdict (spec 004 US1)
    check: Any = None  # guard.CheckInput for the report check
    outcome: Any = None  # (CaseFile) -> (winner, tie) on the same data: questions by value (spec 007 FR-006)


def case_facts(case: CaseFile) -> list[str]:
    out = []
    if case.profile.age:
        out.append(f"age {case.profile.age}")
    if case.usage:
        out.append("usage: " + ", ".join(u.lower() for u in case.usage))
    out += [x[0].lower() + x[1:] for x in fz_app.constraint_lines(case)]
    if case.priorities:
        out.append("priorities: " + ", ".join(p.criterion.replace("_", " ") for p in case.priorities))
    out.append(f"{case.annual_km:,} km per year" + (" (assumed)" if km_assumed(case) else ""))
    for x in case.cars:  # spec 008 FR-027: a used car is labelled as used, an assumed year as assumed
        if x.condition == "USED":
            yr = (f"~{x.year} (assumed)" if x.year_assumed else str(x.year)) if x.year else "year unknown"
            km = f", {x.mileage_km:,} km" if x.mileage_km else ""
            out.append(f"{x.label or x.request_text}: used, {yr}{km}")
    if len(case.cars) > 1 and any(x.condition != "USED" for x in case.cars):  # spec 004 FR-029
        why = (
            "the level of the version you named"
            if case.compare_level_source == "USER_TRIM"
            else ("the cheapest version on sale; name a version to change it")
        )
        out.append(f"compared at the {case.compare_level.lower()} equipment level ({why})")
    return out


def _checked_costs(
    estimates: list[tco.TcoEstimate], ages: dict[str, int | None], notices: list[dict[str, Any]]
) -> dict[str, float]:
    """Sense check on the result (spec 004 FR-027): a yearly cost outside the configured range is an error upstream
    (EUR 513,672/year from a unit error). It is shown flagged and never scored."""
    out: dict[str, float] = {}
    for e in estimates:
        if energy_missing(e):  # spec 006 FR-014: a cost without its energy line is not compared
            continue
        r = sense.tco_per_year(e.annual_total, ages.get(e.car_id))
        if r.ok:
            out[e.car_id] = e.annual_total
        else:
            notices.append(notice(f"{e.label}: ownership cost {r.message} looks wrong; shown, not scored", "warning"))
    return out


def period_totals(estimates: list[tco.TcoEstimate], costs: dict[str, float]) -> dict[str, float]:
    """Total over the ownership period, running costs plus the value lost, for the cars whose running cost is
    compared (chat 5821ac77). Empty unless every one of them has its value loss: a total without it would make
    the car with unknown depreciation look cheaper."""
    cars = [e for e in estimates if e.car_id in costs]
    if not cars or not all(tco.depreciation_known(e) for e in cars):
        return {}
    return {e.car_id: e.period_total for e in cars}


def per_100km(estimates: list[tco.TcoEstimate]) -> dict[str, float]:
    """Energy cost per 100 km per car (spec 006 FR-023), only where the energy line could be computed."""
    out = {}
    for e in estimates:
        item = next((i for i in e.items if i.kind == "ENERGY"), None)
        if item is not None and item.estimate is not None and item.estimate.eur_per_100km is not None:
            out[e.car_id] = item.estimate.eur_per_100km
    return out


def _reg_year(x: Any, car: dict[str, Any], year: int | None) -> int | None:
    if x.condition == "USED" and x.age_years is not None and year is not None:
        return year - x.age_years
    v = car["variant"]
    return getattr(v, "model_year_from", None) or getattr(v, "generation_years_from", None) or year


def verdict_extras(keyed: list[Any], tcars: list[tco.TcoCar], estimates: list[tco.TcoEstimate], case: CaseFile,
                   year: int | None, market: list[dict[str, Any]] | None = None,
                   today: date | None = None,
                   curves: dict[str, tuple[float, ...]] | None = None) -> dict[str, Any]:  # fmt: skip
    """The DGT label of every car and the break-even of an electrified car against a combustion one (spec 006
    FR-015, FR-016): computed by code, with the rule and the inputs. The payback counts the value each car loses
    (`curves`: total cost year by year); without it no payback is claimed (chat 5821ac77)."""
    labels = {}
    for (x, car), tc in zip(keyed, tcars, strict=True):
        lb = incentives.env_label(tc.powertrain, tc.range_wltp, tc.fuel, _reg_year(x, car, year))
        labels[tc.car_id] = {"label": lb.label, "rule": lb.rule, "source_url": lb.source_url}
    out: dict[str, Any] = {"labels": labels}
    run = {e.car_id: e.annual_total for e in estimates if not energy_missing(e)}
    elec = [t for t in tcars if t.powertrain in incentives.ELECTRIFIED]
    comb = [t for t in tcars if t.powertrain not in incentives.ELECTRIFIED]
    region = getattr(case.profile, "region_code", None)
    views = {t.car_id: incentives.view(market or [], today or date.today(), region, t.powertrain)
             for t in elec}  # fmt: skip
    if any(views.values()):
        out["incentives"] = views
    if len(elec) == 1 and len(comb) == 1:
        e, c0 = elec[0], comb[0]
        sub = incentives.subsidy(views.get(e.car_id, []))
        cv = curves or {}
        b = incentives.break_even(_buy_price(e), _buy_price(c0), run.get(e.car_id), run.get(c0.car_id),
                                  subsidy_eur=sub, ownership_years=case.ownership_years,
                                  curve_e=cv.get(e.car_id), curve_c=cv.get(c0.car_id))  # fmt: skip
        out["break_even"] = {"electrified_car_id": e.car_id, "against_car_id": c0.car_id, "verdict": b.verdict,
                             "electrified_label": e.label, "against_label": c0.label,
                             "years": b.years, "beyond_ownership": b.beyond_ownership, "inputs": b.inputs,
                             "ownership_years": case.ownership_years, "subsidy_eur": sub}  # fmt: skip
    return out


def _buy_price(t: tco.TcoCar) -> float | None:
    """What the car costs to buy: a used car's sourced used price, never its new price (spec 008 FR-023)."""
    return t.used_price_eur if t.condition == "USED" else t.price_eur


async def _energy_metrics(c: TurnContext, keyed: list[Any], estimates: list[tco.TcoEstimate]) -> None:
    """FR-022 (spec 006), one event per report: cars without an energy line, EV values rejected by rule, weighted
    plug-in figures blocked from the energy cost. Metrics only: never fails the report."""
    try:
        key = {car["variant"].id: x.key for x, car in keyed}
        missing = {key.get(e.car_id, e.car_id): energy_missing(e) for e in estimates if energy_missing(e)}
        ev = await acquisition.ev_counts(list(key))
        if missing or ev["ev_rejected"] or ev["weighted_blocked"]:
            await record_intake(c, "ENERGY_REPORT", energy_missing=missing, **ev)
    except Exception:  # noqa: BLE001 - metrics only
        return


async def _market_facts(c: TurnContext) -> list[dict[str, Any]]:
    store = getattr(c.ports, "market_facts", None)
    if store is None:
        return []
    try:
        return list(await store.load())
    except Exception:  # noqa: BLE001 - incentives are context; the report is built without them
        return []


def energy_missing(e: tco.TcoEstimate) -> list[str]:
    return next((i.missing for i in e.items if i.kind == "ENERGY" and i.missing), [])


def energy_notices(estimates: list[tco.TcoEstimate], names: dict[str, str], lang: str | None) -> list[dict[str, Any]]:
    """One warning per car whose energy cost cannot be computed, naming the missing inputs (spec 006 FR-001)."""
    out = []
    for e in estimates:
        if miss := energy_missing(e):
            what = ", ".join(energy_input(m, lang) for m in miss)
            out.append(notice(t("energy_missing", lang, car=names.get(e.car_id, e.label), missing=what), "warning",
                              car_id=e.car_id, area="energy"))  # fmt: skip
    return out


KEY_AREAS = ("specs", "price", "maintenance", "reliability")


PERSONAS = ("BUYER", "PERFORMANCE", "EXPERT")
USED_AREAS = {"used_price": "price_used", "used_issues": "wear"}


def limits_from(case: CaseFile, fz: dict[str, Any] | None) -> list[vd.Limit]:
    """Budget and monthly findings from the feasibility checks (spec 007 FR-017): only a clear 'does not fit'
    with both numbers; 'used ones fit' or 'unknown' is not a limit."""
    by_key = {x.key: x.variant_id for x in case.cars}
    out: list[vd.Limit] = []
    for r in (fz or {}).get("results", []):
        vid = by_key.get(r["car_key"])
        for ch in r["checks"]:
            if vid is None or ch["verdict"] != "DOES_NOT_FIT" or ch["check"] not in ("BUDGET", "RUNNING_COST"):
                continue
            nums = [n["value"] for n in ch["compared"] if n.get("value") is not None]
            if len(nums) < 2:
                continue
            kind = "OVER_BUDGET" if ch["check"] == "BUDGET" else "OVER_MONTHLY"
            out.append(vd.Limit(vid, kind, float(nums[0]), float(nums[-1])))  # type: ignore[arg-type]
    return out


def persona_counterfactual(case: CaseFile, outcome: Any) -> vd.OtherProfile | None:
    """Same data, another persona's weights (spec 007 FR-018): the first persona with a different clear winner."""
    mine, _ = outcome(case)
    for p in PERSONAS:
        if p == case.persona:
            continue
        probe = case.model_copy(update={"persona": p, "weight_adjustments": {}, "weights_excluded": [],
                                        "weights_overridden": False, "weights": {}, "priorities": []})  # fmt: skip
        win, tie = outcome(probe)
        if win and not tie and win != mine:
            return vd.OtherProfile(p, win)
    return None


async def _insights(
    c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]], tcars: list[tco.TcoCar],
    costs: dict[str, float], crit: CriteriaScore | None, sims: dict[str, Any], rates: tco.TcoRates, lang: str,
    limits: list[vd.Limit] | None = None, other: vd.OtherProfile | None = None,
    used_prices: dict[str, float | None] | None = None,
    totals: dict[str, float] | None = None, curves: dict[str, tuple[float, ...]] | None = None,
) -> tuple[Any, Any, dict[str, Any], GuardInput]:  # fmt: skip
    """Insights → verdict → the verdict card (spec 004 FR-001, FR-009)."""
    rel = {s.car_id: s.parts.get("reliability") for s in crit.cars} if crit else {}
    energy = {t.car_id: _energy_price(t, rates) for t in tcars}
    values = [
        insight_values(
            car, annual_cost=costs.get(car["variant"].id),
            reliability_score=(rel.get(car["variant"].id).score if rel.get(car["variant"].id) else None),
            energy_eur_per_unit=energy.get(car["variant"].id),
            accel_0_100=getattr(sims.get(car["variant"].id), "t_0_100", None),
            retention_curve=None if recent_make(c)(getattr(car["variant"], "make", None))
            else (c.ports.ref.feasibility or {}).get("depreciation"),
            used=x.condition == "USED", used_price_eur=(used_prices or {}).get(x.key),
            period_total=(totals or {}).get(car["variant"].id), cost_curve=(curves or {}).get(car["variant"].id, ()),
        )
        for x, car in keyed
    ]  # fmt: skip
    model = c.ports.ref.criteria
    weights = weights_for(case, model) if model else {}
    profile = ins.Profile(weights=weights, annual_km=case.annual_km, years=_years(case, rates))
    iset = ins.build(values, profile, ins.rules_from_config(c.ports.ref.insights))
    names = {car["variant"].id: short_name(car["variant"]) for _, car in keyed}
    unmet = await acquisition.unmet_areas([car["variant"].id for _, car in keyed])
    young = {car["variant"].id for _, car in keyed if _new_gen(car, _year(c))}
    gaps = [f"{names[vid]}: {a}" for vid in names for a in KEY_AREAS
            if a in unmet.get(vid, set()) and not (a == "reliability" and vid in young)]  # fmt: skip
    used_missing = [
        vd.UsedMissing(vid, tuple(m for a, m in USED_AREAS.items() if a in unmet.get(vid, set())))
        for vid in (car["variant"].id for x, car in keyed if x.condition == "USED")
    ]
    used_missing = [u for u in used_missing if u.missing]
    gaps += [f"{names[u.car_id]}: {a}" for u in used_missing for a, m in USED_AREAS.items() if m in u.missing]
    classes = [car["variant"].vehicle_class for _, car in keyed]
    v = vd.build(crit, iset, gaps=gaps, different_needs=vd.very_different(classes), limits=limits or [],
                 other_profile=other, used_missing=used_missing)  # fmt: skip
    block = report_text.verdict_block(v, iset, names, lang, case.ownership_years)
    has = {t for t, ok in (("tco", bool(costs)), ("price", "official_price_es" in _any_values(values)),
                           ("consumption", "consumption" in _any_values(values))) if ok}  # fmt: skip
    has |= {i.attribute for i in iset.insights}
    check = GuardInput(frozenset(has), frozenset(iset.ties), v.tie, tuple(sorted(set(names.values()))),
                       costlier=costlier_names(iset, names))  # fmt: skip
    return iset, v, block, check


def costlier_names(iset: Any, names: dict[str, str]) -> tuple[str, ...]:
    """The cars whose total over the period (running + value lost) is meaningfully higher than the cheapest one:
    the text may never call them the saving (chat 5821ac77)."""
    period = iset.get("tco_period") if iset is not None else None
    if period is None or not period.meaningful:
        return ()
    best = set(period.tiers[0])
    return tuple(sorted(names[c.car_id] for c in period.cars if c.car_id not in best and c.car_id in names))


def _years(case: CaseFile, rates: tco.TcoRates) -> int:
    return case.ownership_years or rates.horizon_years


def km_assumed(case: CaseFile) -> bool:
    return case.basis.get("annual_km", "ASSUMED") == "ASSUMED" and not case.annual_km_stated


def assumption_lines(case: CaseFile, rates: tco.TcoRates, lang: str | None) -> list[str]:
    """One short line for what the costs assume and the user never said (annual km, years of ownership), with the
    value and an invitation to correct it (chat 5821ac77: 15,000 km a year was assumed silently)."""
    km = km_assumed(case)
    yrs = case.ownership_years is None or case.basis.get("ownership_years", "ASSUMED") == "ASSUMED"
    if not km and not yrs:
        return []
    key = "assumed_km_years" if km and yrs else "assumed_km" if km else "assumed_years"
    return [t(key, lang, km=report_text.thousands(case.annual_km, lang), years=_years(case, rates))]


def _year(c: TurnContext) -> int | None:
    clock = getattr(c.ports, "clock", None)
    return clock.now().year if clock is not None else None


def _new_gen(car: dict[str, Any], year: int | None) -> int | None:
    return new_generation_since(getattr(car["variant"], "generation_years_from", None), year)


def _new_generation_notices(keyed: list[Any], year: int | None, lang: str | None) -> list[dict[str, Any]]:
    """A generation on sale for under two years has no reliability history: said once, not counted as a gap."""
    return [notice(t("new_generation", lang, car=short_name(car["variant"]), year=since), "info")
            for _, car in keyed if (since := _new_gen(car, year)) is not None]  # fmt: skip


def _abroad_notices(keyed: list[Any], lang: str | None) -> list[dict[str, Any]]:
    """A car not sold in Spain or the EU (chat 2026-11-06): its data come from its market, its price only from a
    European source; without one, no euro price is given (spec 009 FR-009)."""
    out = []
    for x, car in keyed:
        key = markets.abroad_note(x.market, new_price(car) is not None)
        if key is not None:
            out.append(notice(t(key, lang, car=short_name(car["variant"]), market=market_name(x.market, lang)),
                              "info", car_key=x.key))  # fmt: skip
    return out


def _any_values(values: list[Any]) -> set[str]:
    return {k for cv in values for k in cv.values}


def usage_context(case: CaseFile) -> UsageContext:
    """What the energy model needs from the case (spec 006): km, daily distance, climate, usage, home charging."""
    return UsageContext(annual_km=case.annual_km, daily_km=case.needs.daily_km, climate=case.profile.climate,
                        usage=tuple(case.usage),
                        home_charging=getattr(case.profile, "home_charging", None) or "UNKNOWN")  # fmt: skip


def recent_make(c: TurnContext) -> Callable[[str | None], bool]:
    """A make new in the Spanish market (makes.yaml): no class depreciation curve for it (spec 006 FR-018)."""
    reg = getattr(c.ports.ref, "makes", None)
    return reg.new_in_market if reg is not None else (lambda _make: False)


def _energy_price(t: tco.TcoCar, r: tco.TcoRates) -> float:
    if t.powertrain == "BEV":
        return r.energy.home.value
    return r.diesel_eur_per_l if t.fuel == "diesel" else r.fuel_eur_per_l


def _age(x: Any, v: Any, c: TurnContext, notices: list[dict[str, Any]], lang: str) -> int | None:
    """A used car is costed at its age, never as new (spec 008 FR-022): an assumed year is said in a notice; a car
    with no age at all (a case from before 008) gets one assumed here."""
    if x.condition != "USED":
        return x.age_years
    now = _year(c) or 2026
    age, how = x.age_years, None
    if age is None:
        cfg = dict((c.ports.ref.search or {}).get("intake") or {})
        age, how = used.assumed_age(x.mileage_km, getattr(v, "generation_years_from", None),
                                    getattr(v, "generation_years_to", None), now,
                                    km_per_year=int(cfg.get("km_per_year_used", used.KM_PER_YEAR_USED)),
                                    default=int(cfg.get("default_used_age", used.DEFAULT_USED_AGE)))  # fmt: skip
    elif x.year_assumed:
        how = f"{x.mileage_km:,} km at ~15,000 km a year" if x.mileage_km else "no year given"
    if how is not None:
        text = t("used_age_assumed", lang, car=short_name(v), age=age, how=how)
        if all(n.get("text") != text for n in notices):
            notices.append(notice(text, "info"))
    return max(1, age)


@dataclass
class UsedFacts:
    """What a used car is worth and covered by now (spec 008 FR-023, FR-026)."""

    year: int
    price: used.UsedPrice | None
    warranty: used.Warranty


def _used_facts(keyed: list[Any], ages: dict[str, int | None], c: TurnContext, notices: list[dict[str, Any]],
                lang: str) -> dict[str, UsedFacts]:  # fmt: skip
    now = _year(c) or 2026
    out: dict[str, UsedFacts] = {}
    for x, car in keyed:
        if x.condition != "USED":
            continue
        year = x.year or now - (ages.get(x.key) or 1)
        price = used_price(car, year)
        w = used.warranty_status(year, warranty_years(car), now, assumed=x.year_assumed or x.year is None)
        out[x.key] = UsedFacts(year, price, w)
        name = short_name(car["variant"])
        if price is None:
            notices.append(notice(t("used_price_missing", lang, car=name, year=year), "info", car_key=x.key))
        if w.state != "UNKNOWN":
            assumed = (
                {"ru": ", год предположен", "es": ", año supuesto"}.get(lang, ", year assumed") if w.assumed else ""
            )
            key = "warranty_remaining" if w.state == "REMAINING" else "warranty_expired"
            notices.append(notice(t(key, lang, car=name, year=year, assumed=assumed, years=f"{w.years:g}",
                                    until=w.until), "info", car_key=x.key))  # fmt: skip
    return out


def used_lines(case: CaseFile, facts: dict[str, UsedFacts]) -> list[str]:
    """The used cars' own figures for the report (FR-027): year (stated or assumed), mileage, price, warranty."""
    out = []
    for x in case.cars:
        u = facts.get(x.key)
        if u is None:
            continue
        bits = [f"{x.label or x.request_text}: USED, year {u.year}" + (" (assumed)" if x.year_assumed else "")]
        if x.mileage_km:
            bits.append(f"{x.mileage_km:,} km")
        bits.append(f"price used €{u.price.eur:,.0f} (sourced)" if u.price else "price used: no sourced data")
        if u.warranty.state != "UNKNOWN":
            bits.append(f"maker's warranty {'until' if u.warranty.state == 'REMAINING' else 'expired in'} "
                        f"{u.warranty.until}" + (" (assumed year)" if u.warranty.assumed else ""))  # fmt: skip
        else:
            bits.append("maker's warranty: no sourced terms")
        out.append("; ".join(bits))
    return out


async def compute(c: TurnContext, case: CaseFile, notices: list[dict[str, Any]], lang: str = "en") -> Computed:
    keyed = [(x, await load_car(x.variant_id)) for x in case.cars if x.variant_id]
    cars = [car for _, car in keyed]
    race = run_race(cars, case.race_settings.model_dump() if case.race_settings else None)
    sims = {r.car_id: r for r in race.results}
    today = c.ports.clock.now().date().isoformat() if getattr(c.ports, "clock", None) is not None else None
    rates = tco.TcoRates.from_config({**(c.ports.ref.rates or {}), "today": today}, case.rates_override.model_dump())
    curve = (c.ports.ref.feasibility or {}).get("depreciation") or {}
    use = usage_context(case)
    recent = recent_make(c)
    stated = understanding.stated_for_cars(case.stated_energy, [(x.key, car["variant"].powertrain) for x, car in keyed])
    ages = {x.key: _age(x, car["variant"], c, notices, lang) for x, car in keyed}
    usedf = _used_facts(keyed, ages, c, notices, lang)

    def up(x: Any) -> float | None:
        u = usedf.get(x.key)
        return u.price.eur if u is not None and u.price is not None else None

    tcars = [await tco_car(car, _cond(x.condition), ages[x.key], x.mileage_km, curve, use,
                                   recent(getattr(car["variant"], "make", None)), stated.get(x.key), up(x))
             for x, car in keyed]  # fmt: skip
    estimates = tco.like_for_like([tco.compute(t, rates, case.annual_km, case.ownership_years) for t in tcars])
    costs = _checked_costs(estimates, {car["variant"].id: ages[x.key] for x, car in keyed}, notices)
    totals = period_totals(estimates, costs)
    curves = {tc.car_id: cv for tc in tcars if tc.car_id in totals
              and (cv := tco.cost_curve(tc, rates, case.annual_km))}  # fmt: skip
    years = _years(case, rates)
    eff = per_100km(estimates)
    notices += energy_notices(estimates, {car["variant"].id: short_name(car["variant"]) for car in cars}, lang)
    await _energy_metrics(c, keyed, estimates)
    no_energy = {x.key for x, car in keyed
                 if any(e.car_id == car["variant"].id and energy_missing(e) for e in estimates)}  # fmt: skip
    # the energy notice names the missing input; "specs: minimum not reached" for the same car only repeats it
    notices[:] = [n for n in notices if not (n.get("area") == "specs" and n.get("car_key") in no_energy
                                             and "car_id" not in n)]  # fmt: skip
    year = _year(c)
    young = {x.key for x, car in keyed if _new_gen(car, year)}
    notices[:] = [n for n in notices if not (n.get("area") == "reliability" and n.get("car_key") in young)]
    notices += _new_generation_notices(keyed, year, lang)
    notices += _abroad_notices(keyed, lang)
    facts = [
        car_facts(
            car,
            sims.get(car["variant"].id),
            condition=_cond(x.condition),
            age_years=ages[x.key],
            annual_cost_eur=costs.get(car["variant"].id),
            year=year,
            energy_eur_per_100km=eff.get(car["variant"].id),
            mileage_km=x.mileage_km,
            used_price_eur=up(x),
            period_cost_eur=totals.get(car["variant"].id),
            period_years=years,
        )
        for x, car in keyed
    ]
    model = c.ports.ref.criteria
    weights = weights_for(case, model)
    crit = score(facts, weights, model) if facts and weights else None

    def outcome(probe: CaseFile) -> tuple[str | None, bool]:
        """The same data scored for another profile (pure: no search, no model)."""
        puse = usage_context(probe)
        est = tco.like_for_like([tco.compute(replace(t, use=puse), rates, probe.annual_km, probe.ownership_years)
                                 for t in tcars])  # fmt: skip
        cost = _checked_costs(est, {car["variant"].id: ages[x.key] for x, car in keyed}, [])
        tot = period_totals(est, cost)
        eff_p = per_100km(est)
        fs = [car_facts(car, sims.get(car["variant"].id), condition=_cond(x.condition), age_years=ages[x.key],
                            annual_cost_eur=cost.get(car["variant"].id), year=year,
                            energy_eur_per_100km=eff_p.get(car["variant"].id), mileage_km=x.mileage_km,
                            used_price_eur=up(x), period_cost_eur=tot.get(car["variant"].id),
                            period_years=_years(probe, rates)) for x, car in keyed]  # fmt: skip
        w = weights_for(probe, model)
        r = score(fs, w, model) if fs and w else None
        return (r.winner_car_id, r.tie) if r else (None, False)

    fz = await _feasibility(c, case)
    other = persona_counterfactual(case, outcome) if crit is not None and len(keyed) > 1 else None
    iset, verdict, vblock, check = await _insights(c, case, keyed, tcars, costs, crit, sims, rates, lang,
                                                   limits_from(case, fz), other,
                                                   {x.key: up(x) for x, _ in keyed}, totals, curves)  # fmt: skip
    extras = verdict_extras(
        keyed,
        tcars,
        estimates,
        case,
        year,
        await _market_facts(c),
        c.ports.clock.now().date() if getattr(c.ports, "clock", None) is not None else None,
        curves,
    )
    vblock.update(extras)
    blocks = await _blocks(c, case, keyed, race, crit, estimates, iset, fz)
    eb = electric.build(cars, tcars, estimates, rates, extras["labels"], lang, extras.get("incentives"))
    if eb is not None:
        blocks.append(eb)
    said = bool(verdict.trade_off and (verdict.trade_off.break_even_years or verdict.trade_off.no_payback))
    names_e = {t.car_id: short_name(car["variant"]) for t, car in zip(tcars, cars, strict=True)}
    if lines := report_text.electric_lines(eb, extras.get("break_even"), names_e, lang, years_said=said):
        vblock["profile_notes"] = [*vblock.get("profile_notes", []), *lines]
    assumed = assumption_lines(case, rates, lang) if cars else []  # what the costs assume, said with the value
    vblock["profile_notes"] = [*vblock.get("profile_notes", []), *assumed]
    out_notices = list(notices)
    if case.unmapped_wishes:
        out_notices.append(notice("Not assessable with data: " + ", ".join(case.unmapped_wishes)))
    panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
    gaps_by_car = {x["car_key"]: [a["area"] for a in x["areas"] if a["findable"] and a["status"] != "COMPLETE"]
                   for x in (panel or {}).get("cars", [])}  # fmt: skip
    names = {car["variant"].id: short_name(car["variant"]) for car in cars}
    sugg = (
        report_text.suggestions_block(
            suggestions.build(verdict, iset, all_new=all(x.condition != "USED" for x, _ in keyed),
                              gaps_by_car=gaps_by_car),
            names, lang,
        )
        if cars
        else None
    )  # fmt: skip
    if not any(gaps_by_car.values()):
        vblock["find"] = False  # nothing left a "find it" could bring (spec 007 F)
    head = [vblock, *([sugg] if sugg else [])]
    body = order_blocks(case.persona, out_notices + blocks, cars=len(cars))
    body = annotate_sections(case.persona, body, c.ports.ref.layouts or {})
    ordered = [*head, *body] if cars else []
    summary = summary_for_llm(cars, race, crit)
    summary["ownership_cost"] = ownership_facts(estimates, totals, years, names, iset)
    summary["insights"] = report_text.insights_for_llm(iset, verdict, names, lang, case.ownership_years)
    if lines:
        summary["electrified"] = lines  # spec 006 T050: the code-built sentences, numbers from code
    summary["assumptions"] = assumed
    summary["profile_focus"] = profile_focus(case, crit, verdict, names, lang)
    summary["section_depth"] = depths(case.persona, c.ports.ref.layouts or {})  # spec 004 FR-019
    if ul := used_lines(case, usedf):  # spec 008 FR-027: say these figures are for a used car
        summary["used_cars"] = ul
    return Computed(blocks=ordered, facts=summary, criteria=crit, cars=cars, tco=estimates, race=race,
                    insights=iset, verdict=verdict, check=check, outcome=outcome)  # fmt: skip


def ownership_facts(estimates: list[tco.TcoEstimate], totals: dict[str, float], years: int,
                    names: dict[str, str], iset: Any = None) -> dict[str, Any]:  # fmt: skip
    """Ownership cost for the writer (chat 5821ac77): the total over the period including depreciation is THE
    comparison; running costs per year are labelled as without depreciation. Code decides which car is cheaper."""
    cars = []
    for e in estimates:
        dep = next((i.five_year_eur for i in e.items if i.kind == "DEPRECIATION"), None)
        row: dict[str, Any] = {
            "car": names.get(e.car_id, e.label),
            "running_costs_per_year_without_depreciation_eur": e.annual_total,
            "items": [{"kind": i.kind, "annual_eur": i.annual_eur, "basis": i.basis} for i in e.items],
        }
        if e.car_id in totals:
            row["total_over_the_period_including_depreciation_eur"] = totals[e.car_id]
            row["depreciation_over_the_period_eur"] = dep
        cars.append(row)
    out: dict[str, Any] = {"period_years": years, "cars": cars}
    period = iset.get("tco_period") if iset is not None else None
    if len(totals) >= 2 and period is not None and period.meaningful:
        cheap = [names.get(c, c) for c in period.tiers[0]]
        out["cheaper_to_own_over_the_period"] = " / ".join(cheap)
        out["costlier_to_own_over_the_period"] = list(costlier_names(iset, names))
        out["difference_over_the_period_eur"] = period.diff
        out["rule"] = (
            "Compare ownership cost ONLY on the totals including depreciation. Running costs per year "
            "may be quoted only as 'running costs (without depreciation)' and never as a saving."
        )
    elif len(totals) >= 2:
        out["about_the_same_over_the_period"] = True
        out["rule"] = (
            "The totals including depreciation are about the same: name no car as cheaper to own. Running "
            "costs per year may be quoted only as 'running costs (without depreciation)'."
        )
    else:
        out["rule"] = (
            "Depreciation is not known for every car: these are running costs only. Say so; never claim "
            "that a car saves money or pays back."
        )
    return out


def profile_focus(
    case: CaseFile, crit: CriteriaScore | None, verdict: Any, names: dict[str, str], lang: str
) -> dict[str, Any]:  # fmt: skip
    """For the writer (spec 007 FR-018): lead with the criteria this user weights highest, and the code facts
    about what the profile changes. The model may phrase these, never add to them."""
    weights = crit.weights if crit is not None else {}
    top = sorted(((k, w) for k, w in weights.items() if w > 0), key=lambda kw: (-kw[1], kw[0]))[:3]
    p = case.profile
    who = [x for x in (case.persona, p.family, p.driving_style, p.age_band) if x and x != "UNKNOWN"]
    return {
        "top_criteria": [{"criterion": k, "weight": round(w, 1)} for k, w in top],
        "profile": who,
        "ownership_years": case.ownership_years,
        "annual_km": case.annual_km,
        "notes": report_text.profile_lines(verdict, names, lang, case.ownership_years) if verdict else [],
    }


async def _feasibility(c: TurnContext, case: CaseFile) -> dict[str, Any] | None:
    if not fz_app.has_constraints(case) or c.ports.feasibility is None:
        return None
    return await fz_app.evaluate(case, c.ports.ref.feasibility, c.ports.ref.rates or {}, c.ports.clock.now().year,
                                 c.ports.feasibility)  # fmt: skip


async def _blocks(
    c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]], race: Any, crit: CriteriaScore | None,
    estimates: list[tco.TcoEstimate], iset: Any, fz: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    cars = [car for _, car in keyed]
    model = c.ports.ref.criteria
    try:
        views = await car_view.view(case)  # spec 010 FR-036: the version line of each car
    except Exception:  # noqa: BLE001 - a label, never a reason to fail the report
        views = {}
    blocks: list[dict[str, Any]] = [
        case_summary_block(
            case.persona,
            case_facts(case),
            [
                {
                    "key": x.key,
                    "label": x.label or x.request_text,
                    "condition": x.condition,
                    "year": x.year,
                    "variant_label": (views.get(x.key) or {}).get("variant_label"),
                    "variant_id": x.variant_id,
                }
                for x in case.cars
            ],  # fmt: skip
        ),
        spec_table(cars, {}, iset),
        metric_bars(cars),
        race_block(race, _predicted(case)),
        sources_block(cars),
    ]
    if crit is not None:
        blocks.append(criteria_block(crit, model, case.unmapped_wishes, weight_breakdown(case, model)))
    ages = {x.variant_id: x.age_years for x in case.cars if x.variant_id}
    if fz is not None:  # spec 003: the verdict stays visible
        fz_block = fz_app.block(case, fz)
        if fz_block is not None:
            blocks.append(fz_block)
    for extra in (
        engineering_block(cars, c.ports.ref.explainers),
        manufacturer_block(cars),
        reliability_block(cars, ages),
        reviews_block(cars),
        value_retention_block(cars, (c.ports.ref.feasibility or {}).get("depreciation") or {}, recent_make(c)),
        _data_panel(c, case, keyed),  # spec 004 FR-014: one panel instead of a warning per section
    ):
        if extra is not None:
            blocks.append(extra)
    if estimates:
        ids = [x for e in estimates for i in e.items for x in i.evidence_ids]
        tb = tco_block(estimates, await evidence_refs(ids))
        tb["annual_km_assumed"] = km_assumed(case)  # chat 5821ac77: said on the block, not only in the text
        blocks.append(tb)
    return blocks


def _data_panel(c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]]) -> dict[str, Any] | None:
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    budget_used = bool(case.budget.max_eur) and case.budget.intent in ("USED", "ANY")
    areas = {x.key: research_plan.areas_for(case.persona, criteria, x.condition, budget_used) for x, _ in keyed}
    clock = getattr(c.ports, "clock", None)
    now = clock.now() if clock is not None else None
    rows = [(x.key, short_name(car["variant"]), car) for x, car in keyed]
    return data_panel_block(rows, areas, now, case.last_values or None, case.find_tried)


def _predicted(case: CaseFile) -> str | None:
    if case.prediction is None:
        return None
    return next((x.variant_id for x in case.cars if x.key == case.prediction.winner_key), None)


def _cond(condition: str) -> str:
    return "USED" if condition == "USED" else "NEW"
