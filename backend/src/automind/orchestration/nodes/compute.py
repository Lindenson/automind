"""compute: deterministic numbers and blocks for a report or an answer (FR-027..FR-032, R5).

Criteria scores, metrics, drag race and blocks come only from code (constitution III), ordered per
persona (FR-030). Weight changes recompute from cached data without research (FR-029, SC-009).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.application import compose, research
from automind.application import feasibility as fz_app
from automind.domain import insights as ins
from automind.domain import research_plan, sense, suggestions, tco
from automind.domain import verdict as vd
from automind.domain.casefile import CaseFile
from automind.domain.criteria import CriteriaScore, score, weight_breakdown, weights_for
from automind.domain.report_layout import annotate_sections, depths, order_blocks
from automind.orchestration import report_text
from automind.orchestration.guard import CheckInput as GuardInput
from automind.orchestration.runner import TurnContext

from .common import notice


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
    out.append(f"{case.annual_km:,} km per year")
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
        r = sense.tco_per_year(e.annual_total, ages.get(e.car_id))
        if r.ok:
            out[e.car_id] = e.annual_total
        else:
            notices.append(notice(f"{e.label}: ownership cost {r.message} looks wrong; shown, not scored", "warning"))
    return out


KEY_AREAS = ("specs", "price", "maintenance", "reliability")


async def _insights(
    c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]], tcars: list[tco.TcoCar],
    costs: dict[str, float], crit: CriteriaScore | None, sims: dict[str, Any], rates: tco.TcoRates, lang: str,
) -> tuple[Any, Any, dict[str, Any], GuardInput]:  # fmt: skip
    """Insights → verdict → the verdict card (spec 004 FR-001, FR-009)."""
    rel = {s.car_id: s.parts.get("reliability") for s in crit.cars} if crit else {}
    energy = {t.car_id: _energy_price(t, rates) for t in tcars}
    values = [
        compose.insight_values(
            car, annual_cost=costs.get(car["variant"].id),
            reliability_score=(rel.get(car["variant"].id).score if rel.get(car["variant"].id) else None),
            energy_eur_per_unit=energy.get(car["variant"].id),
            accel_0_100=getattr(sims.get(car["variant"].id), "t_0_100", None),
            retention_curve=(c.ports.ref.feasibility or {}).get("depreciation"),
        )
        for _, car in keyed
    ]  # fmt: skip
    model = c.ports.ref.criteria
    weights = weights_for(case, model) if model else {}
    profile = ins.Profile(weights=weights, annual_km=case.annual_km)
    iset = ins.build(values, profile, ins.rules_from_config(c.ports.ref.insights))
    names = {car["variant"].id: compose.short_name(car["variant"]) for _, car in keyed}
    unmet = await research.unmet_areas([car["variant"].id for _, car in keyed])
    gaps = [f"{names[vid]}: {a}" for vid in names for a in KEY_AREAS if a in unmet.get(vid, set())]
    classes = [car["variant"].vehicle_class for _, car in keyed]
    v = vd.build(crit, iset, gaps=gaps, different_needs=vd.very_different(classes))
    block = report_text.verdict_block(v, iset, names, lang)
    has = {t for t, ok in (("tco", bool(costs)), ("price", "official_price_es" in _any_values(values)),
                           ("consumption", "consumption" in _any_values(values))) if ok}  # fmt: skip
    has |= {i.attribute for i in iset.insights}
    check = GuardInput(frozenset(has), frozenset(iset.ties), v.tie, tuple(sorted(set(names.values()))))
    return iset, v, block, check


def _any_values(values: list[Any]) -> set[str]:
    return {k for cv in values for k in cv.values}


def _energy_price(t: tco.TcoCar, r: tco.TcoRates) -> float:
    if t.powertrain == "BEV":
        return r.electricity_eur_per_kwh
    return r.diesel_eur_per_l if t.fuel == "diesel" else r.fuel_eur_per_l


async def compute(c: TurnContext, case: CaseFile, notices: list[dict[str, Any]], lang: str = "en") -> Computed:
    keyed = [(x, await compose.load_car(x.variant_id)) for x in case.cars if x.variant_id]
    cars = [car for _, car in keyed]
    race = compose.run_race(cars, case.race_settings.model_dump() if case.race_settings else None)
    sims = {r.car_id: r for r in race.results}
    rates = tco.TcoRates.from_config(c.ports.ref.rates or {}, case.rates_override.model_dump())
    tcars = [await compose.tco_car(car, _cond(x.condition), x.age_years, x.mileage_km) for x, car in keyed]
    estimates = [tco.compute(t, rates, case.annual_km) for t in tcars]
    costs = _checked_costs(estimates, {car["variant"].id: x.age_years for x, car in keyed}, notices)
    facts = [
        compose.facts(
            car,
            sims.get(car["variant"].id),
            condition=_cond(x.condition),
            age_years=x.age_years,
            annual_cost_eur=costs.get(car["variant"].id),
        )
        for x, car in keyed
    ]
    model = c.ports.ref.criteria
    weights = weights_for(case, model)
    crit = score(facts, weights, model) if facts and weights else None

    def outcome(probe: CaseFile) -> tuple[str | None, bool]:
        """The same data scored for another profile (pure: no search, no model)."""
        est = [tco.compute(t, rates, probe.annual_km) for t in tcars]
        cost = _checked_costs(est, {car["variant"].id: x.age_years for x, car in keyed}, [])
        fs = [compose.facts(car, sims.get(car["variant"].id), condition=_cond(x.condition), age_years=x.age_years,
                            annual_cost_eur=cost.get(car["variant"].id)) for x, car in keyed]  # fmt: skip
        w = weights_for(probe, model)
        r = score(fs, w, model) if fs and w else None
        return (r.winner_car_id, r.tie) if r else (None, False)

    iset, verdict, vblock, check = await _insights(c, case, keyed, tcars, costs, crit, sims, rates, lang)
    blocks = await _blocks(c, case, keyed, race, crit, estimates, iset)
    out_notices = list(notices)
    if case.unmapped_wishes:
        out_notices.append(notice("Not assessable with data: " + ", ".join(case.unmapped_wishes)))
    panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
    gaps_by_car = {x["car_key"]: [a["area"] for a in x["areas"] if a["findable"] and a["status"] != "COMPLETE"]
                   for x in (panel or {}).get("cars", [])}  # fmt: skip
    names = {car["variant"].id: compose.short_name(car["variant"]) for car in cars}
    sugg = (
        report_text.suggestions_block(
            suggestions.build(verdict, iset, all_new=all(x.condition != "USED" for x, _ in keyed),
                              gaps_by_car=gaps_by_car),
            names, lang,
        )
        if cars
        else None
    )  # fmt: skip
    head = [vblock, *([sugg] if sugg else [])]
    body = order_blocks(case.persona, out_notices + blocks, cars=len(cars))
    body = annotate_sections(case.persona, body, c.ports.ref.layouts or {})
    ordered = [*head, *body] if cars else []
    summary = compose.summary_for_llm(cars, race, crit)
    summary["ownership_cost"] = [
        {
            "label": e.label,
            "annual_eur": e.annual_total,
            "five_year_eur": e.five_year_total,
            "items": [{"kind": i.kind, "annual_eur": i.annual_eur, "basis": i.basis} for i in e.items],
        }
        for e in estimates
    ]
    summary["insights"] = report_text.insights_for_llm(iset, verdict, names, lang)
    summary["section_depth"] = depths(case.persona, c.ports.ref.layouts or {})  # spec 004 FR-019
    return Computed(blocks=ordered, facts=summary, criteria=crit, cars=cars, tco=estimates, race=race,
                    insights=iset, verdict=verdict, check=check, outcome=outcome)  # fmt: skip


async def _blocks(
    c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]], race: Any, crit: CriteriaScore | None,
    estimates: list[tco.TcoEstimate], iset: Any,
) -> list[dict[str, Any]]:  # fmt: skip
    cars = [car for _, car in keyed]
    model = c.ports.ref.criteria
    blocks: list[dict[str, Any]] = [
        compose.case_summary_block(
            case.persona,
            case_facts(case),
            [
                {"key": x.key, "label": x.label or x.request_text, "condition": x.condition, "year": x.year}
                for x in case.cars
            ],
        ),
        compose.spec_table(cars, {}, iset),
        compose.metric_bars(cars),
        compose.race_block(race, _predicted(case)),
        compose.sources_block(cars),
    ]
    if crit is not None:
        blocks.append(compose.criteria_block(crit, model, case.unmapped_wishes, weight_breakdown(case, model)))
    ages = {x.variant_id: x.age_years for x in case.cars if x.variant_id}
    if fz_app.has_constraints(case) and c.ports.feasibility is not None:  # spec 003: the verdict stays visible
        fz = await fz_app.evaluate(case, c.ports.ref.feasibility, c.ports.ref.rates or {}, c.ports.clock.now().year,
                                   c.ports.feasibility)  # fmt: skip
        fz_block = fz_app.block(case, fz)
        if fz_block is not None:
            blocks.append(fz_block)
    for extra in (
        compose.engineering_block(cars, c.ports.ref.explainers),
        compose.manufacturer_block(cars),
        compose.reliability_block(cars, ages),
        compose.reviews_block(cars),
        compose.value_retention_block(cars, (c.ports.ref.feasibility or {}).get("depreciation") or {}),
        _data_panel(c, case, keyed),  # spec 004 FR-014: one panel instead of a warning per section
    ):
        if extra is not None:
            blocks.append(extra)
    if estimates:
        ids = [x for e in estimates for i in e.items for x in i.evidence_ids]
        blocks.append(compose.tco_block(estimates, await compose.evidence_refs(ids)))
    return blocks


def _data_panel(c: TurnContext, case: CaseFile, keyed: list[tuple[Any, dict[str, Any]]]) -> dict[str, Any] | None:
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    budget_used = bool(case.budget.max_eur) and case.budget.intent in ("USED", "ANY")
    areas = {x.key: research_plan.areas_for(case.persona, criteria, x.condition, budget_used) for x, _ in keyed}
    clock = getattr(c.ports, "clock", None)
    now = clock.now() if clock is not None else None
    rows = [(x.key, compose.short_name(car["variant"]), car) for x, car in keyed]
    return compose.data_panel_block(rows, areas, now, case.last_values or None)


def _predicted(case: CaseFile) -> str | None:
    if case.prediction is None:
        return None
    return next((x.variant_id for x in case.cars if x.key == case.prediction.winner_key), None)


def _cond(condition: str) -> str:
    return "USED" if condition == "USED" else "NEW"
