"""A car area's pages, one pipeline per page (spec 004 FR-032): relevance (the brand rule for brand areas, else the
rules and the relevance role) → the site reader's table, or the extraction role → the checks (`validate`) → the
page's evidence and rows stored (`persist`). Pages run concurrently; the model calls are bounded per job here and in
total by the gateway.

Errors: BudgetExceeded propagates (the job stops); a failing extraction drops that page only (one failing source
never fails the job); a store failure (`PipelineStoreUnavailable`) propagates (the job fails)."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from automind.acquisition.domain import relevance as rel
from automind.acquisition.parsing.extraction import areas
from automind.acquisition.parsing.extraction import extract as ex
from automind.acquisition.pipeline.contracts import JobSpec, PageTally
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.parse import read_tables
from automind.acquisition.pipeline.persist import persist_extraction, persist_reading
from automind.acquisition.pipeline.plan import known_makes
from automind.acquisition.pipeline.relevance import PageJudge, job_relevance_target, llm_per_job
from automind.acquisition.ports import AcqPorts
from automind.shared.contracts.web import Page, WebDoc
from automind.shared.metering.usage import BudgetExceeded
from automind.shared.research_order import plan as research_plan

OFF_TOPIC = ("OTHER_VARIANT", "NOT_ABOUT_CAR")  # relevance verdicts that drop a page
UNSURE = ("UNCERTAIN", "MULTI_VARIANT")  # verdicts that send an extraction's claims to the validator role


async def read_car_pages(ports: AcqPorts, v: VariantFacts, job: JobSpec, pages: list[Page],
                         target: str) -> PageTally:  # fmt: skip
    """Read every page for the car (`target`: the car as the roles are told it); returns what they gave."""
    tgt, gens = job_relevance_target(v, ports)
    judge = PageJudge(ports, v, tgt, gens, target, job.area)
    known = await ports.stores.values.known_values(v.id)
    tables = await read_tables(ports, v, pages) if job.area in areas.SPEC_AREAS else {}
    reader = _CarPages(ports, v, job, target, judge, known, tables)
    await asyncio.gather(*(reader.read(p) for p in pages))
    return reader.tally


class _CarPages:
    """One job's page reader; `tally` collects what the pages gave (safe under concurrency: no await between a
    read and a write of it)."""

    def __init__(self, ports: AcqPorts, v: VariantFacts, job: JobSpec, target: str, judge: PageJudge,
                 known: dict[str, float], tables: dict[str, Any]) -> None:  # fmt: skip
        self.ports, self.v, self.job, self.target, self.judge = ports, v, job, target, judge
        self.known, self.tables = known, tables
        self.brand = job.area in research_plan.BRAND_AREAS
        self.makes = known_makes(ports)
        self.sem = asyncio.Semaphore(llm_per_job(ports))
        self.tally = PageTally(tabled=set(tables))

    async def read(self, p: Page) -> None:
        """One page: relevance, then its table or its extraction, checked and stored."""
        r = await self._relevance(p)
        if r.verdict in OFF_TOPIC:
            self.tally.rejected_page(p.url, r.verdict)
            return
        self.tally.docs += 1
        d = p.as_doc()
        if d.url in self.tables:
            a, rj = await persist_reading(self.ports, self.v, self.job.area, d, self.tables[d.url], self.known,
                                          self.tally.values_rejected, p)  # fmt: skip
            self.tally.reader += a
        else:
            out = await self._extract(d)
            if out is None:
                return
            async with self.sem:
                a, rj = await persist_extraction(self.ports, self.v, self.job.area, d, out, self.target,
                                                 r.verdict in UNSURE, p, self.known, self.tally.values_rejected,
                                                 car_year=self.job.car_year)  # fmt: skip
        self.tally.stored(p.url, a, rj)

    async def _relevance(self, p: Page) -> rel.Relevance:
        if self.brand:  # the brand's own pages: any page about the make counts
            return rel.judge_brand(rel.PageFacts(p.url, p.title, p.text), self.v.make, self.makes)
        return await self.judge(p)

    async def _extract(self, d: WebDoc) -> BaseModel | None:
        """The extraction role's reading; None when it failed or says the page is about another car."""
        try:
            async with self.sem:
                out = await ex.extract(self.ports.llm, self.ports.ref.prompts, self.job.area, self.target, d)
        except BudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - one failing source never fails the job
            return None
        if out is None or not getattr(out, "is_about_variant", True):
            return None
        return out
