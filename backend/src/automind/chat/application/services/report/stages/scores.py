"""Stage scores (spec 002, spec 007 FR-006/FR-018): the criteria scores of the compared cars from their facts, and
the same data scored for another profile (`SameDataScores`), which questions by value and the persona
counterfactual use — no search, no model call."""

from __future__ import annotations

from dataclasses import dataclass, replace

from automind.chat.application.services.report.case_facts import condition_of, usage_context, years_of
from automind.chat.application.services.report.contracts import KeyedCars
from automind.chat.application.services.report.facts.scoring_inputs import car_facts
from automind.chat.application.services.report.stages.ownership import (
    Ownership,
    checked_costs,
    per_100km,
    period_totals,
)
from automind.chat.application.services.report.stages.used_cars import UsedFacts, used_price_of
from automind.chat.domain.assessment import metrics as scoring
from automind.chat.domain.assessment.criteria import CriteriaModel, CriteriaScore, score, weights_for
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.shared.contracts.json import JsonObject


@dataclass
class ScoreInputs:
    """What scoring reads besides the case: the cars, their race results, ages, costs and used prices."""

    keyed: KeyedCars
    sims: JsonObject
    ages: dict[str, int | None]
    used: dict[str, UsedFacts]
    year: int | None
    rates: tco.TcoRates


def scores(case: CaseFile, inp: ScoreInputs, own: Ownership, model: CriteriaModel) -> CriteriaScore | None:
    """The criteria scores of the compared cars (None without facts or weights)."""
    facts = facts_of(inp, own.costs, own.eff, own.totals, own.years)
    weights = weights_for(case, model)
    return score(facts, weights, model) if facts and weights else None


def facts_of(inp: ScoreInputs, costs: dict[str, float], eff: dict[str, float], totals: dict[str, float],
             years: int) -> list[scoring.CarFacts]:  # fmt: skip
    """The scoring facts of each car with the costs of this run."""
    return [
        car_facts(
            car,
            inp.sims.get(car["variant"].id),
            condition=condition_of(x.condition),
            age_years=inp.ages[x.key],
            annual_cost_eur=costs.get(car["variant"].id),
            year=inp.year,
            energy_eur_per_100km=eff.get(car["variant"].id),
            mileage_km=x.mileage_km,
            used_price_eur=used_price_of(inp.used, x.key),
            period_cost_eur=totals.get(car["variant"].id),
            period_years=years,
        )
        for x, car in inp.keyed
    ]


class SameDataScores:
    """The same data scored for another profile (pure: no search, no model): (winner car id, tie)."""

    def __init__(self, inp: ScoreInputs, tcars: list[tco.TcoCar], model: CriteriaModel) -> None:
        self.inp, self.tcars, self.model = inp, tcars, model

    def __call__(self, probe: CaseFile) -> tuple[str | None, bool]:
        inp = self.inp
        puse = usage_context(probe)
        est = tco.like_for_like([tco.compute(replace(t, use=puse), inp.rates, probe.annual_km, probe.ownership_years)
                                 for t in self.tcars])  # fmt: skip
        cost = checked_costs(est, {car["variant"].id: inp.ages[x.key] for x, car in inp.keyed}, [])
        fs = facts_of(inp, cost, per_100km(est), period_totals(est, cost), years_of(probe, inp.rates))
        w = weights_for(probe, self.model)
        r = score(fs, w, self.model) if fs and w else None
        return (r.winner_car_id, r.tie) if r else (None, False)
