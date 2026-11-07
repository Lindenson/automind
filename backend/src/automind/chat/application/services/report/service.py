"""The report service (FR-027..FR-032, R5; spec 012 S8): deterministic numbers and blocks for a report or an answer.
Criteria scores, metrics, drag race and blocks come only from code (constitution III), ordered per persona
(FR-030). A weights change recomputes from stored data without research (FR-029, SC-009)."""

from __future__ import annotations

from datetime import date, datetime

from automind.acquisition import api as acquisition
from automind.chat.application.ports import Ports
from automind.chat.application.services.feasibility import feasibility as fz_app
from automind.chat.application.services.report.blocks.notice import Notice
from automind.chat.application.services.report.contracts import Computed, IntakeLog, KeyedCars, ReportWording
from automind.chat.application.services.report.facts.car import load_car
from automind.chat.application.services.report.facts.race import run_race
from automind.chat.application.services.report.stages.assemble import assemble_blocks
from automind.chat.application.services.report.stages.case_notices import car_notices
from automind.chat.application.services.report.stages.ownership import energy_missing, price_ownership
from automind.chat.application.services.report.stages.present import present, writer_summary
from automind.chat.application.services.report.stages.scores import SameDataScores, ScoreInputs, scores
from automind.chat.application.services.report.stages.used_cars import car_age, used_facts, used_price_of
from automind.chat.application.services.report.stages.verdict import (
    judge,
    limits_from,
    persona_counterfactual,
    verdict_extras,
)
from automind.chat.domain.case import CaseFile
from automind.chat.domain.cost import tco
from automind.shared.contracts.json import JsonObject


class ReportService:
    """Computes a report from stored data; `words` says it in the person's language, `log` records intake events."""

    def __init__(self, ports: Ports, words: ReportWording, log: IntakeLog) -> None:
        self.ports, self.words, self.log = ports, words, log

    async def run(self, case: CaseFile, notices: list[Notice], lang: str = "en") -> Computed:
        ref, words, now = self.ports.ref, self.words, self._now()
        year = now.year if now is not None else None
        keyed = [(x, await load_car(x.variant_id)) for x in case.cars if x.variant_id]
        race = run_race([car for _, car in keyed], case.race_settings.model_dump() if case.race_settings else None)
        sims = {r.car_id: r for r in race.results}
        rates = self._rates(case)
        ages = {x.key: car_age(x, car["variant"], ref, year, notices, lang, words) for x, car in keyed}
        used = used_facts(keyed, ages, year, notices, lang, words)
        own = await price_ownership(case, keyed, ages, used, rates, ref, notices, lang, words)
        await self._energy_metrics(keyed, own.estimates)
        car_notices(keyed, year, notices, lang, words)
        inp = ScoreInputs(keyed, sims, ages, used, year, rates)
        crit, outcome = scores(case, inp, own, ref.criteria), SameDataScores(inp, own.tcars, ref.criteria)
        fz = await self._feasibility(case)
        other = persona_counterfactual(case, outcome) if crit is not None and len(keyed) > 1 else None
        judged = await judge(ref, case, keyed, own, crit, sims, rates, year, lang, words, limits_from(case, fz),
                             other, {x.key: used_price_of(used, x.key) for x, _ in keyed})  # fmt: skip
        extras = verdict_extras(keyed, own.tcars, own.estimates, case, year, await self._market_facts(),
                                self._today(), own.curves)  # fmt: skip
        judged.block.update(extras)
        blocks = await assemble_blocks(ref, case, keyed, race, crit, own.estimates, judged.insights, fz, self._now())
        shown = present(ref, case, keyed, own, judged, extras, blocks, notices, rates, lang, words)
        facts = writer_summary(ref, case, keyed, race, crit, own, judged, shown, used, lang, words)
        return Computed(blocks=shown.blocks, facts=facts, criteria=crit, cars=[car for _, car in keyed],
                        tco=own.estimates, race=race, insights=judged.insights, verdict=judged.verdict,
                        check=judged.check, outcome=outcome)  # fmt: skip

    def _now(self) -> datetime | None:
        clock = getattr(self.ports, "clock", None)
        return clock.now() if clock is not None else None

    def _today(self) -> date | None:
        now = self._now()
        return now.date() if now is not None else None

    def _rates(self, case: CaseFile) -> tco.TcoRates:
        today = self._today()
        return tco.TcoRates.from_config({**(self.ports.ref.rates or {}), "today": today.isoformat() if today else None},
                                        case.rates_override.model_dump())  # fmt: skip

    async def _energy_metrics(self, keyed: KeyedCars, estimates: list[tco.TcoEstimate]) -> None:
        """FR-022 (spec 006), one event per report: cars without an energy line, EV values rejected by rule, weighted
        plug-in figures blocked from the energy cost. Metrics only: never fails the report."""
        try:
            key = {car["variant"].id: x.key for x, car in keyed}
            missing = {key.get(e.car_id, e.car_id): energy_missing(e) for e in estimates if energy_missing(e)}
            ev = await acquisition.ev_counts(list(key))
            if missing or ev["ev_rejected"] or ev["weighted_blocked"]:
                await self.log("ENERGY_REPORT", energy_missing=missing, **ev)
        except Exception:  # noqa: BLE001 - metrics only
            return

    async def _market_facts(self) -> list[JsonObject]:
        store = getattr(self.ports, "market_facts", None)
        if store is None:
            return []
        try:
            return list(await store.load())
        except Exception:  # noqa: BLE001 - incentives are context; the report is built without them
            return []

    async def _feasibility(self, case: CaseFile) -> JsonObject | None:
        if not fz_app.has_constraints(case) or self.ports.feasibility is None:
            return None
        return await fz_app.evaluate(case, self.ports.ref.feasibility, self.ports.ref.rates or {},
                                     self.ports.clock.now().year, self.ports.feasibility)  # fmt: skip
