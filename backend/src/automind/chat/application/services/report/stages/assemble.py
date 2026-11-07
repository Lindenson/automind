"""Stage assemble: the report's blocks in their natural order — case summary, spec table, metric bars, race,
sources, criteria, feasibility, engineering, manufacturer, reliability, reviews, value retention, the data panel
and the ownership cost (the persona's layout orders them later, spec 004 FR-019)."""

from __future__ import annotations

from datetime import datetime

from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.report.blocks import car_view
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
from automind.chat.application.services.report.case_facts import case_facts, km_assumed, recent_make
from automind.chat.application.services.report.contracts import KeyedCars
from automind.chat.application.services.report.facts.car import short_name
from automind.chat.domain.assessment.criteria import CriteriaScore, weight_breakdown
from automind.chat.domain.assessment.dragrace import RaceResult
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.chat.domain.verdict.insights import InsightSet
from automind.shared.contracts.config import Reference
from automind.shared.contracts.json import JsonObject
from automind.shared.research_order import plan as research_plan


async def assemble_blocks(ref: Reference, case: CaseFile, keyed: KeyedCars, race: RaceResult,
                          crit: CriteriaScore | None, estimates: list[tco.TcoEstimate], iset: InsightSet,
                          fz: JsonObject | None, now: datetime | None) -> list[JsonObject]:  # fmt: skip
    cars = [car for _, car in keyed]
    model = ref.criteria
    try:
        views = await car_view.view(case)  # spec 010 FR-036: the version line of each car
    except Exception:  # noqa: BLE001 - a label, never a reason to fail the report
        views = {}
    summary = [{"key": x.key, "label": x.label or x.request_text, "condition": x.condition, "year": x.year,
                "variant_label": (views.get(x.key) or {}).get("variant_label"), "variant_id": x.variant_id}
               for x in case.cars]  # fmt: skip
    blocks: list[JsonObject] = [
        case_summary_block(case.persona, case_facts(case), summary),
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
        engineering_block(cars, ref.explainers),
        manufacturer_block(cars),
        reliability_block(cars, ages),
        reviews_block(cars),
        value_retention_block(cars, (ref.feasibility or {}).get("depreciation") or {}, recent_make(ref)),
        _data_panel(case, keyed, now),  # spec 004 FR-014: one panel instead of a warning per section
    ):
        if extra is not None:
            blocks.append(extra)
    if estimates:
        ids = [x for e in estimates for i in e.items for x in i.evidence_ids]
        tb = tco_block(estimates, await evidence_refs(ids))
        tb["annual_km_assumed"] = km_assumed(case)  # chat 5821ac77: said on the block, not only in the text
        blocks.append(tb)
    return blocks


def _data_panel(case: CaseFile, keyed: KeyedCars, now: datetime | None) -> JsonObject | None:
    criteria = [p.criterion for p in case.priorities] + [k for k, w in case.weights.items() if w > 0]
    budget_used = bool(case.budget.max_eur) and case.budget.intent in ("USED", "ANY")
    areas = {x.key: research_plan.areas_for(case.persona, criteria, x.condition, budget_used) for x, _ in keyed}
    rows = [(x.key, short_name(car["variant"]), car) for x, car in keyed]
    return data_panel_block(rows, areas, now, case.last_values or None, case.find_tried)


def _predicted(case: CaseFile) -> str | None:
    if case.prediction is None:
        return None
    return next((x.variant_id for x in case.cars if x.key == case.prediction.winner_key), None)
