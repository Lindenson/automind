"""compute: deterministic numbers and blocks for a report or an answer (FR-027..FR-032, R5).

Criteria scores, metrics, drag race and blocks come only from code (constitution III), ordered per
persona (FR-030). Weight changes recompute from cached data without research (FR-029, SC-009).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.application import compose
from automind.domain import tco
from automind.domain.casefile import CaseFile
from automind.domain.criteria import CriteriaScore, score, weights_for
from automind.domain.report_layout import order_blocks
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


def case_facts(case: CaseFile) -> list[str]:
    out = []
    if case.profile.age:
        out.append(f"age {case.profile.age}")
    if case.usage:
        out.append("usage: " + ", ".join(u.lower() for u in case.usage))
    if case.budget.max_eur:
        out.append(f"budget up to €{case.budget.max_eur:,}")
    if case.priorities:
        out.append("priorities: " + ", ".join(p.criterion.replace("_", " ") for p in case.priorities))
    out.append(f"{case.annual_km:,} km per year")
    return out


async def compute(c: TurnContext, case: CaseFile, notices: list[dict[str, Any]]) -> Computed:
    keyed = [(x, await compose.load_car(x.variant_id)) for x in case.cars if x.variant_id]
    cars = [car for _, car in keyed]
    race = compose.run_race(cars, case.race_settings.model_dump() if case.race_settings else None)
    sims = {r.car_id: r for r in race.results}
    rates = tco.TcoRates.from_config(c.ports.ref.rates or {}, case.rates_override.model_dump())
    estimates = [
        tco.compute(await compose.tco_car(car, _cond(x.condition), x.age_years, x.mileage_km), rates, case.annual_km)
        for x, car in keyed
    ]
    costs = {e.car_id: e.annual_total for e in estimates}
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
    blocks: list[dict[str, Any]] = [
        compose.case_summary_block(
            case.persona,
            case_facts(case),
            [
                {"key": x.key, "label": x.label or x.request_text, "condition": x.condition, "year": x.year}
                for x in case.cars
            ],
        ),
        compose.spec_table(cars, {}),
        compose.metric_bars(cars),
        compose.race_block(race, _predicted(case)),
        compose.sources_block(cars),
    ]
    if crit is not None:
        blocks.append(compose.criteria_block(crit, model, case.unmapped_wishes))
    ages = {x.variant_id: x.age_years for x in case.cars if x.variant_id}
    for extra in (
        compose.engineering_block(cars),
        compose.manufacturer_block(cars),
        compose.reliability_block(cars, ages),
        compose.reviews_block(cars),
    ):
        if extra is not None:
            blocks.append(extra)
    if estimates:
        ids = [x for e in estimates for i in e.items for x in i.evidence_ids]
        blocks.append(compose.tco_block(estimates, await compose.evidence_refs(ids)))
    out_notices = list(notices)
    if case.unmapped_wishes:
        out_notices.append(notice("Not assessable with data: " + ", ".join(case.unmapped_wishes)))
    have = {n.get("text", "") for n in out_notices}
    for n in await compose.section_notices([(car["variant"].id, car["variant"].label) for car in cars]):
        label = n["text"].split(":")[0]
        if not any(label in h and "insufficient" in h for h in have):
            out_notices.append(n)
    ordered = order_blocks(case.persona, out_notices + blocks, cars=len(cars))
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
    return Computed(blocks=ordered, facts=summary, criteria=crit, cars=cars, tco=estimates, race=race)


def _predicted(case: CaseFile) -> str | None:
    if case.prediction is None:
        return None
    return next((x.variant_id for x in case.cars if x.key == case.prediction.winner_key), None)


def _cond(condition: str) -> str:
    return "USED" if condition == "USED" else "NEW"
