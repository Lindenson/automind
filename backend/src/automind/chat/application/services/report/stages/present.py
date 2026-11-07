"""Stage present: the report as the person sees it and the writer is told it — the electric section and its
sentences, what the costs assume, the suggestions, the persona's block order (spec 004 FR-019, FR-030), and the
validated facts for the writer (numbers only from code, constitution III)."""

from __future__ import annotations

from dataclasses import dataclass, field

from automind.chat.application.services.report.blocks import electric
from automind.chat.application.services.report.blocks.notice import Notice, notice
from automind.chat.application.services.report.case_facts import assumption_lines
from automind.chat.application.services.report.contracts import KeyedCars, ReportWording
from automind.chat.application.services.report.facts.car import short_name
from automind.chat.application.services.report.stages.ownership import Ownership, ownership_facts
from automind.chat.application.services.report.stages.used_cars import UsedFacts, used_lines
from automind.chat.application.services.report.stages.verdict import Judged, profile_focus
from automind.chat.application.services.report.writer_facts import summary_for_llm
from automind.chat.domain.assessment.criteria import CriteriaScore
from automind.chat.domain.assessment.dragrace import RaceResult
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.chat.domain.verdict import suggestions
from automind.chat.domain.verdict.report_layout import annotate_sections, depths, order_blocks
from automind.shared.contracts.config import Reference
from automind.shared.contracts.json import JsonObject


@dataclass
class Presented:
    """What the report shows and what the writer is told about it."""

    blocks: list[JsonObject]  # in the persona's order, the verdict card first
    electric_lines: list[str] = field(default_factory=list)
    assumed: list[str] = field(default_factory=list)


def present(ref: Reference, case: CaseFile, keyed: KeyedCars, own: Ownership, judged: Judged,
            extras: JsonObject, blocks: list[JsonObject], notices: list[Notice], rates: tco.TcoRates,
            lang: str, words: ReportWording) -> Presented:  # fmt: skip
    """The blocks in the persona's order with the verdict card and the next steps first, the notices placed, and the
    lines the writer needs (electric, assumptions)."""
    cars = [car for _, car in keyed]
    vblock, verdict, iset = judged.block, judged.verdict, judged.insights
    eb = electric.build(cars, own.tcars, own.estimates, rates, extras["labels"], lang, extras.get("incentives"))
    if eb is not None:
        blocks.append(eb)
    said = bool(verdict.trade_off and (verdict.trade_off.break_even_years or verdict.trade_off.no_payback))
    names_e = {t.car_id: short_name(car["variant"]) for t, car in zip(own.tcars, cars, strict=True)}
    if lines := words.electric_lines(eb, extras.get("break_even"), names_e, lang, years_said=said):
        vblock["profile_notes"] = [*vblock.get("profile_notes", []), *lines]
    assumed = assumption_lines(case, rates, lang, words) if cars else []  # what the costs assume, said with the value
    vblock["profile_notes"] = [*vblock.get("profile_notes", []), *assumed]
    out_notices = list(notices)
    if case.unmapped_wishes:
        out_notices.append(notice("Not assessable with data: " + ", ".join(case.unmapped_wishes)))
    panel = next((b for b in blocks if b.get("type") == "data_panel"), None)
    gaps_by_car = {x["car_key"]: [a["area"] for a in x["areas"] if a["findable"] and a["status"] != "COMPLETE"]
                   for x in (panel or {}).get("cars", [])}  # fmt: skip
    names = {car["variant"].id: short_name(car["variant"]) for car in cars}
    sugg = (
        words.suggestions_block(
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
    body = order_blocks(case.persona, [*(dict(n) for n in out_notices), *blocks], cars=len(cars))
    body = annotate_sections(case.persona, body, ref.layouts or {})
    return Presented([*head, *body] if cars else [], lines, assumed)


def writer_summary(ref: Reference, case: CaseFile, keyed: KeyedCars, race: RaceResult, crit: CriteriaScore | None,
                   own: Ownership, judged: Judged, shown: Presented, used: dict[str, UsedFacts], lang: str,
                   words: ReportWording) -> JsonObject:  # fmt: skip
    """The validated facts the writer is given."""
    cars = [car for _, car in keyed]
    names = {car["variant"].id: short_name(car["variant"]) for car in cars}
    iset, verdict = judged.insights, judged.verdict
    summary = summary_for_llm(cars, race, crit)
    summary["ownership_cost"] = ownership_facts(own.estimates, own.totals, own.years, names, iset)
    summary["insights"] = words.insights_for_llm(iset, verdict, names, lang, case.ownership_years)
    if shown.electric_lines:
        summary["electrified"] = shown.electric_lines  # spec 006 T050: the code-built sentences, numbers from code
    summary["assumptions"] = shown.assumed
    summary["profile_focus"] = profile_focus(case, crit, verdict, names, lang, words)
    summary["section_depth"] = depths(case.persona, ref.layouts or {})  # spec 004 FR-019
    if ul := used_lines(case, used):  # spec 008 FR-027: say these figures are for a used car
        summary["used_cars"] = ul
    return summary
