"""The research service (R8, R14; FR-019..FR-023, FR-044): the jobs of a research — one per car × area — created as
rows (a job already DONE is never run again after a restart), each run by the acquisition engine within the turn's
budget and the job timeout (a failing job never fails the turn; near a limit it pauses, never cancels), and what
the research leaves: areas still below their minimum said as "insufficient data" (constitution XI). The graph fans
the jobs out and runs the rounds; this service does the work of each step."""

from __future__ import annotations

import asyncio
from typing import Any

from automind.acquisition import api as acquisition
from automind.chat.application.ports import Ports
from automind.chat.application.services.report.blocks.notice import notice
from automind.chat.application.services.research.contracts import ResearchEvents, ResearchWording
from automind.chat.application.services.research.rounds import minimum_met, need_of
from automind.chat.domain.case import CaseCar, CaseFile
from automind.shared.metering.usage import BudgetExceeded, TurnBudget
from automind.shared.research_order import plan as rp

Short = tuple[str, str]  # (car key, area) still below its minimum
_SEARCHING = ("searching", "researching")  # engine stages shown as "searching" in the grid
_READING = ("reading", "relevance", "validating")  # engine stages shown as "reading"


class ResearchService:
    def __init__(self, ports: Ports, budget: TurnBudget, events: ResearchEvents, chat_id: str, turn_id: str) -> None:
        self.ports, self.budget, self.events = ports, budget, events
        self.chat_id, self.turn_id = chat_id, turn_id

    async def create(self, case: CaseFile, jobs: list[rp.Job]) -> list[dict[str, Any]]:
        """Job rows for the plan's jobs, each cell of the grid shown at once as queued (spec 004 FR-023)."""
        out = []
        for j in jobs:
            row = await self.ports.jobs.create(self.chat_id, self.turn_id, j.variant_id, j.area, j.round)
            out.append({"job_id": row.id, "car_key": j.car_key, "variant_id": j.variant_id, "area": j.area,
                        "round": j.round, "fresh": j.fresh, "escalate": j.escalate})  # fmt: skip
        for j in jobs:
            car = next((x for x in case.cars if x.key == j.car_key), None)
            await self.events.emit("progress", {"car": (car.label or car.request_text) if car else j.car_key,
                                                "car_key": j.car_key, "area": j.area, "state": "queued",
                                                "accepted": None, "round": j.round})  # fmt: skip
        return out

    async def run_job(self, job: dict[str, Any], case: CaseFile) -> dict[str, Any]:
        """One job: reused when already DONE, dropped when the car was corrected meanwhile, paused near a limit,
        else researched by the engine. Returns the job's result for the round."""
        row = await self.ports.jobs.get(job["job_id"])
        if row is not None and row.status == "DONE":  # resumed after a restart: never redo finished work
            return {**job, "ok": True, "reused": True, "minimum_met": None}
        car = next((x for x in case.cars if x.key == job["car_key"]), None)
        if car is None or car.variant_id != job["variant_id"]:  # corrected meanwhile (spec 005): never the old one
            await self.ports.jobs.mark(job["job_id"], "FAILED", error="superseded by a correction")
            return {**job, "ok": False, "error": None, "minimum_met": None}
        grid = _Grid(self.events, job, car.label or car.request_text)
        pause = self.budget.research_pause()
        if pause is not None:  # near a limit: do not start, ask the user whether to continue (never cancel)
            await grid.progress("paused")
            await self.ports.jobs.mark(job["job_id"], "FAILED", error=f"paused at the {pause} limit")
            return {**job, "ok": False, "error": f"paused: {pause}", "limit": pause}
        await self.ports.jobs.mark(job["job_id"], "RUNNING")
        await grid.progress("searching")
        return await self._acquire(job, car, grid)

    def conclude(self, case: CaseFile, results: list[dict[str, Any]], notices: list[dict[str, Any]],
                 lang: str | None, words: ResearchWording) -> tuple[list[dict[str, Any]], list[Short]]:  # fmt: skip
        """The notices of a finished research (a job that did not complete, an area below its minimum; each said
        once) and the (car key, area) pairs still short. The answer always gets its reserve of the budget."""
        self.budget.allow_answer()  # otherwise the report itself hit the limit (flaky test_limit_pause found it)
        labels = {x.key: x.label or x.request_text for x in case.cars}
        out = list(notices)
        for r in results:
            if not r.get("ok") and r.get("error"):
                text = words.t("job_incomplete", lang, car=labels.get(r["car_key"], r["car_key"]),
                               area=words.area_label(r["area"], lang), error=r["error"][:80])  # fmt: skip
                out.append(notice(text, "warning"))
        short = sorted({(k, a) for (k, a), ok in minimum_met(results).items() if not ok})
        for k, a in short:
            out.append(notice(words.t("short_data", lang, car=labels.get(k, k), area=words.area_label(a, lang)),
                              "warning", car_key=k, area=a))  # fmt: skip
        seen: set[str] = set()  # a job that timed out before and after "continue" is said once
        return [n for n in out if not (n.get("text") in seen or seen.add(n.get("text")))], short  # type: ignore[func-returns-value]

    async def _acquire(self, job: dict[str, Any], car: CaseCar, grid: _Grid) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.budget.limits.job_timeout_s):
                got = await self.ports.acquisition.acquire(  # type: ignore[union-attr]
                    acquisition.AcquireRequest(
                        job_id=job["job_id"], variant_id=job["variant_id"], kinds=[job["area"]], need=need_of(job),
                        round=job["round"], car_year=car.year,
                        market=car.market,  # a car not sold in Spain: researched where it is sold
                    ),
                    grid.stage,
                )  # fmt: skip
                res = got.kinds[0]
        except BudgetExceeded as e:
            await grid.progress("paused")
            await self.ports.jobs.mark(job["job_id"], "FAILED", error=str(e))
            return {**job, "ok": False, "error": str(e), "limit": e.limit}
        except TimeoutError:
            await grid.progress("failed")
            if "job_timeout" not in self.budget.limits_reached:
                self.budget.limits_reached.append("job_timeout")
            await self.ports.jobs.mark(job["job_id"], "FAILED", error="timeout")
            return {**job, "ok": False, "error": "timeout", "limit": "time"}
        state = "done" if res.ok and res.minimum_met else ("partial" if res.ok and res.accepted else "failed")
        await grid.progress(state, res.accepted)
        await self.ports.jobs.mark(job["job_id"], "DONE" if res.ok else "FAILED", docs=res.docs, accepted=res.accepted,
                                   rejected=res.rejected, error=res.error)  # fmt: skip
        return {**job, "ok": res.ok, "minimum_met": res.minimum_met, "error": res.error, "accepted": res.accepted,
                "rejected": res.rejected}  # fmt: skip


class _Grid:
    """One job's cell of the car × area grid (spec 004 FR-023) and its status lines."""

    def __init__(self, events: ResearchEvents, job: dict[str, Any], label: str) -> None:
        self.events, self.job, self.label = events, job, label

    async def progress(self, state: str, accepted: int | None = None) -> None:
        job = self.job
        cell = {"car": self.label, "car_key": job["car_key"], "area": job["area"], "state": state,
                "accepted": accepted, "round": job.get("round", 0)}  # fmt: skip
        await self.events.emit("progress", cell)

    async def stage(self, stage: str, text: str) -> None:
        """The engine's progress callback: a status line, and the grid's cell for the search and reading stages."""
        await self.events.status(stage, text, car=self.label, area=self.job["area"])
        if stage in (*_SEARCHING, *_READING):
            await self.progress("reading" if stage in _READING else "searching")
