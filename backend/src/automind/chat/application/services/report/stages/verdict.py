"""Stage verdict (spec 004 FR-001/FR-009, spec 006 FR-015/FR-016, spec 007 FR-017/FR-018): insights → verdict →
the verdict card, with the gaps that hold it back, the budget and monthly limits, the persona that would choose
otherwise, the DGT labels and the break-even of an electrified car; and what the text must lead with."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from automind.acquisition import api as acquisition
from automind.chat.application.services.report.case_facts import recent_make
from automind.chat.application.services.report.contracts import CheckInput, KeyedCars, LoadedCar, ReportWording
from automind.chat.application.services.report.facts.car import short_name
from automind.chat.application.services.report.facts.scoring_inputs import insight_values
from automind.chat.application.services.report.stages.case_notices import new_gen
from automind.chat.application.services.report.stages.ownership import (
    Ownership,
    buy_price,
    costlier_names,
    energy_missing,
    energy_price,
)
from automind.chat.domain.assessment.criteria import CriteriaScore, Part, weights_for
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.cost import incentives, tco
from automind.chat.domain.verdict import insights as ins
from automind.chat.domain.verdict import verdict as vd
from automind.shared.contracts.config import Reference
from automind.shared.contracts.json import JsonObject

KEY_AREAS = ("specs", "price", "maintenance", "reliability")  # a gap here holds the verdict back
PERSONAS = ("BUYER", "PERFORMANCE", "EXPERT")
USED_AREAS = {"used_price": "price_used", "used_issues": "wear"}


@dataclass
class Judged:
    insights: Any  # domain.verdict.insights.InsightSet
    verdict: vd.Verdict
    block: JsonObject  # the verdict card
    check: CheckInput


async def judge(ref: Reference, case: CaseFile, keyed: KeyedCars, own: Ownership, crit: CriteriaScore | None,
                sims: JsonObject, rates: tco.TcoRates, year: int | None, lang: str, words: ReportWording,
                limits: list[vd.Limit] | None = None, other: vd.OtherProfile | None = None,
                used_prices: dict[str, float | None] | None = None) -> Judged:  # fmt: skip
    """Insights → verdict → the verdict card (spec 004 FR-001, FR-009)."""
    rel = {s.car_id: s.parts.get("reliability") for s in crit.cars} if crit else {}
    energy = {t.car_id: energy_price(t, rates) for t in own.tcars}
    values = [
        insight_values(
            car, annual_cost=own.costs.get(car["variant"].id),
            reliability_score=_score(rel.get(car["variant"].id)),
            energy_eur_per_unit=energy.get(car["variant"].id),
            accel_0_100=getattr(sims.get(car["variant"].id), "t_0_100", None),
            retention_curve=None if recent_make(ref)(getattr(car["variant"], "make", None))
            else (ref.feasibility or {}).get("depreciation"),
            used=x.condition == "USED", used_price_eur=(used_prices or {}).get(x.key),
            period_total=own.totals.get(car["variant"].id), cost_curve=own.curves.get(car["variant"].id, ()),
        )
        for x, car in keyed
    ]  # fmt: skip
    model = ref.criteria
    weights = weights_for(case, model) if model else {}
    profile = ins.Profile(weights=weights, annual_km=case.annual_km, years=case.ownership_years or rates.horizon_years)
    iset = ins.build(values, profile, ins.rules_from_config(ref.insights))
    names = {car["variant"].id: short_name(car["variant"]) for _, car in keyed}
    gaps, used_missing = await _gaps(keyed, names, year)
    classes = [car["variant"].vehicle_class for _, car in keyed]
    v = vd.build(crit, iset, gaps=gaps, different_needs=vd.very_different(classes), limits=limits or [],
                 other_profile=other, used_missing=used_missing)  # fmt: skip
    block = words.verdict_block(v, iset, names, lang, case.ownership_years)
    has = {t for t, ok in (("tco", bool(own.costs)), ("price", "official_price_es" in _any_values(values)),
                           ("consumption", "consumption" in _any_values(values))) if ok}  # fmt: skip
    has |= {i.attribute for i in iset.insights}
    check = CheckInput(frozenset(has), frozenset(iset.ties), v.tie, tuple(sorted(set(names.values()))),
                       costlier=costlier_names(iset, names))  # fmt: skip
    return Judged(iset, v, block, check)


def limits_from(case: CaseFile, fz: JsonObject | None) -> list[vd.Limit]:
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


def verdict_extras(keyed: KeyedCars, tcars: list[tco.TcoCar], estimates: list[tco.TcoEstimate], case: CaseFile,
                   year: int | None, market: list[JsonObject] | None = None,
                   today: date | None = None,
                   curves: dict[str, tuple[float, ...]] | None = None) -> JsonObject:  # fmt: skip
    """The DGT label of every car and the break-even of an electrified car against a combustion one (spec 006
    FR-015, FR-016): computed by code, with the rule and the inputs. The payback counts the value each car loses
    (`curves`: total cost year by year); without it no payback is claimed (chat 5821ac77)."""
    labels = {}
    for (x, car), tc in zip(keyed, tcars, strict=True):
        lb = incentives.env_label(tc.powertrain, tc.range_wltp, tc.fuel, _reg_year(x, car, year))
        labels[tc.car_id] = {"label": lb.label, "rule": lb.rule, "source_url": lb.source_url}
    out: JsonObject = {"labels": labels}
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
        b = incentives.break_even(buy_price(e), buy_price(c0), run.get(e.car_id), run.get(c0.car_id),
                                  subsidy_eur=sub, ownership_years=case.ownership_years,
                                  curve_e=cv.get(e.car_id), curve_c=cv.get(c0.car_id))  # fmt: skip
        out["break_even"] = {"electrified_car_id": e.car_id, "against_car_id": c0.car_id, "verdict": b.verdict,
                             "electrified_label": e.label, "against_label": c0.label,
                             "years": b.years, "beyond_ownership": b.beyond_ownership, "inputs": b.inputs,
                             "ownership_years": case.ownership_years, "subsidy_eur": sub}  # fmt: skip
    return out


def profile_focus(case: CaseFile, crit: CriteriaScore | None, verdict: Any, names: dict[str, str], lang: str,
                  words: ReportWording) -> JsonObject:  # fmt: skip
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
        "notes": words.profile_lines(verdict, names, lang, case.ownership_years) if verdict else [],
    }


async def _gaps(keyed: KeyedCars, names: dict[str, str], year: int | None) -> tuple[list[str], list[vd.UsedMissing]]:
    """The key areas researched without reaching their minimum (a young generation's reliability is no gap), and
    the used cars' missing used price or wear."""
    unmet = await acquisition.unmet_areas([car["variant"].id for _, car in keyed])
    young = {car["variant"].id for _, car in keyed if new_gen(car, year)}
    gaps = [f"{names[vid]}: {a}" for vid in names for a in KEY_AREAS
            if a in unmet.get(vid, set()) and not (a == "reliability" and vid in young)]  # fmt: skip
    used_missing = [
        vd.UsedMissing(vid, tuple(m for a, m in USED_AREAS.items() if a in unmet.get(vid, set())))
        for vid in (car["variant"].id for x, car in keyed if x.condition == "USED")
    ]
    used_missing = [u for u in used_missing if u.missing]
    gaps += [f"{names[u.car_id]}: {a}" for u in used_missing for a, m in USED_AREAS.items() if m in u.missing]
    return gaps, used_missing


def _reg_year(x: CaseCar, car: LoadedCar, year: int | None) -> int | None:
    if x.condition == "USED" and x.age_years is not None and year is not None:
        return year - x.age_years
    v = car["variant"]
    return getattr(v, "model_year_from", None) or getattr(v, "generation_years_from", None) or year


def _any_values(values: list[Any]) -> set[str]:
    return {k for cv in values for k in cv.values}


def _score(part: Part | None) -> float | None:
    return part.score if part is not None else None
