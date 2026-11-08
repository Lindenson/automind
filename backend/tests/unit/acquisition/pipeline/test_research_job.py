"""`ResearchJob.run` over fakes: an area that found nothing still closes its run; a store failure fails the job only
(no exception, a "failed" line, counted); an exhausted budget propagates; the job's scope is reset however it ends.
`PageTally`: a page's outcome as an attempt of its source."""

from __future__ import annotations

from typing import Any

import pytest

from automind.acquisition.pipeline import scope
from automind.acquisition.pipeline.application.ports import (
    AreaRun,
    JobMetrics,
    PipelineStores,
    PipelineStoreUnavailable,
)
from automind.acquisition.pipeline.contracts import JobSpec, PageOutcome, PageTally
from automind.acquisition.pipeline.domain.variant import CarVariant
from automind.acquisition.pipeline.job import STAGE_VERSIONS, ResearchJob
from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.api import Plan, PlannedSource
from automind.shared.contracts.web import Page
from automind.shared.metering.usage import BudgetExceeded

CAR = CarVariant(id="v1", make="Audi", model="A4", generation="B9", variant_name="35 TFSI 150 CV", powertrain="MHEV",
                 body_class=None, generation_years_from=2015, generation_years_to=None, transmission=None, drive=None,
                 market="ES")  # fmt: skip


class _NoWeb:
    """Every search finds nothing."""

    async def search(self, query: str, **_: Any) -> list[Any]:
        return []

    async def get(self, url: str, **_: Any) -> None:
        return None

    def last_reason(self, url: str) -> str:
        return "none"


class _Variants:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    async def load(self, variant_id: str) -> CarVariant | None:
        if self.fail is not None:
            raise self.fail
        return CAR if variant_id == CAR.id else None


class _Values:
    async def known_values(self, variant_id: str) -> dict[str, float]:
        return {}

    async def available(self, variant_id: str) -> set[str]:
        return set()


class _Book:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.runs: list[AreaRun] = []
        self.metrics: list[JobMetrics] = []

    async def used_urls(self, variant_id: str) -> set[str]:
        if self.fail is not None:
            raise self.fail
        return set()

    async def record_metrics(self, job_id: str, metrics: JobMetrics) -> None:
        self.metrics.append(metrics)

    async def area_sources(self, variant_id: str, make: str, area: str, kind: Any) -> list[Any]:
        return []

    async def mark_run(self, run: AreaRun, *, brand_positioning: bool = False) -> None:
        self.runs.append(run)


class _Registry:
    def __init__(self) -> None:
        self.attempts: list[Any] = []

    async def plan(self, area: str, markets: list[str], make: str | None) -> Plan:
        active = PlannedSource(domain="motor.es", market="ES", priority=1, status="active")
        retired = PlannedSource(domain="old.es", market="ES", priority=2, status="retired")
        return Plan(area=area, sources=[active, retired])

    async def sources_for(self, area: str, markets: list[str], n: int) -> list[Any]:
        return []

    async def record(self, attempts: list[Any]) -> None:
        self.attempts += attempts


def _ports(variants: _Variants | None = None, book: _Book | None = None) -> tuple[AcqPorts, list[tuple[str, str]]]:
    from automind.chat.dialog.prompts import load_all  # noqa: PLC0415 - the reference data, read once per test
    from automind.delivery.bootstrap import reference  # noqa: PLC0415

    counted: list[tuple[str, str]] = []
    stores = PipelineStores(variants=variants or _Variants(), evidence=None, values=_Values(), verdicts=None,  # type: ignore[arg-type]  # fakes of the stores a job without pages never calls
                            book=book or _Book())  # fmt: skip
    ports = AcqPorts(llm=None, ref=reference(load_all()), search=_NoWeb(), stores=stores, registry=_Registry(),  # type: ignore[arg-type]  # no model call without pages
                     metrics=lambda name, **kw: counted.append((kw["area"], kw["status"])))  # fmt: skip
    return ports, counted


class _Lines:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    async def __call__(self, stage: str, text: str) -> None:
        self.lines.append((stage, text))


async def test_an_area_that_found_nothing_closes_its_run_with_the_stage_versions() -> None:
    book = _Book()
    ports, counted = _ports(book=book)
    lines = _Lines()
    res = await ResearchJob(ports).run(JobSpec("j1", CAR.id, "reviews"), lines)
    assert res.ok and (res.docs, res.accepted, res.rejected, res.minimum_met) == (0, 0, 0, False)
    assert res.planned == ["motor.es"]  # the plan's active sources only
    assert [(r.area, r.docs, r.registry, r.stage_versions) for r in book.runs] == [
        ("reviews", 0, False, STAGE_VERSIONS)
    ]
    assert book.metrics and book.metrics[0].pages_found == 0
    assert counted == [("reviews", "ok")]
    assert lines.lines[-1] == ("validating", "reviews: 0 accepted, 0 rejected by validation")
    assert scope.current_plan.get() is None and scope.current_candidates.get() is None


async def test_a_store_down_fails_the_job_only() -> None:
    book = _Book()
    ports, counted = _ports(variants=_Variants(PipelineStoreUnavailable("db down")), book=book)
    lines = _Lines()
    res = await ResearchJob(ports).run(JobSpec("j2", CAR.id, "specs"), lines)
    assert not res.ok and res.error == "PipelineStoreUnavailable: db down"
    assert lines.lines == [("researching", "specs: failed (PipelineStoreUnavailable)")]
    assert counted == [("specs", "error")] and book.runs == []
    assert scope.current_plan.get() is None


async def test_an_unknown_variant_fails_the_job() -> None:
    ports, counted = _ports()
    res = await ResearchJob(ports).run(JobSpec("j3", "nope", "reviews"), _Lines())
    assert not res.ok and res.error == "ValueError: unknown variant nope"
    assert counted == [("reviews", "error")]


async def test_an_exhausted_budget_stops_the_research() -> None:
    ports, counted = _ports(book=_Book(BudgetExceeded("search", "search budget spent")))
    with pytest.raises(BudgetExceeded):
        await ResearchJob(ports).run(JobSpec("j4", CAR.id, "reviews"), _Lines())
    assert counted == [("reviews", "budget")]
    assert scope.current_plan.get() is None and scope.current_candidates.get() is None


def test_a_page_outcome_follows_what_it_gave() -> None:
    t = PageTally(tabled={"https://t.es/1"})
    t.rejected_page("https://a.es/1", "OTHER_VARIANT")
    t.stored("https://b.es/1", 3, 1)
    t.stored("https://c.es/1", 0, 2)
    t.stored("https://t.es/1", 0, 0)
    assert t.outcomes == {"https://a.es/1": PageOutcome("rejected", "other_variant"),
                          "https://b.es/1": PageOutcome("accepted", None, 3),
                          "https://c.es/1": PageOutcome("rejected", "values_rejected"),
                          "https://t.es/1": PageOutcome("empty")}  # fmt: skip
    assert (t.accepted, t.rejected, dict(t.off_topic)) == (3, 3, {"other_variant": 1})
    pages = [
        Page(url=u, title="", text="") for u in ("https://a.es/1", "https://b.es/1", "https://t.es/1", "https://x.es/1")
    ]
    assert [p.url for p in t.shadow_pages(pages)] == ["https://a.es/1", "https://b.es/1"]
