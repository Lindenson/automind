"""Spec 011 T057/T058: the prefetch task refreshes what users ask most, before they ask, within its daily budget.

The fixture scenario `bmw520` is asked in two chats: the worker's prefetch refreshes its due area through
`acquisition.api.acquire` (fixture search, fake model); a car whose areas are fresh is left alone; the spend is
journalled on the task and stops at `prefetch.eur_per_day`; with `prefetch.enabled: false` nothing runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.graph.conftest import engine, make_ports, open_web_reference

from automind.acquisition.parsing.infrastructure import wiring as parsing_wiring
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.acquisition.worker import exporter, prefetch, queue
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import HANDLERS
from automind.acquisition.worker.process import Worker
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker

KM77 = {"domain": "km77.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 1,
        "reader": "km77", "tos_checked": "2026-11-02"}  # fmt: skip


def _extractor(system, user):  # noqa: ANN001
    claim = {"attribute": "max_power", "raw_value": "190", "unit": "CV", "excerpt": "190 CV", "scope": "VARIANT"}
    return {"is_about_variant": True, "claims": [claim]}


def _ports(fx: FixtureSearch):  # noqa: ANN202
    llm = FakeLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["validator"] = lambda s, u: {"verdicts": [{"index": 0, "verdict": "OTHER_MARKET"}]}
    ports = engine(make_ports(llm=llm, search=fx))
    ports.ref = open_web_reference(
        favourites=[KM77], favourite_queries={"specs": "{make} {model} {generation} {variant} {sites}"}
    )
    ports.readers = parsing_wiring.yaml_registry([KM77])
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}
    ports.registry = RegistryService(RegistryRepo(cfg), cfg)
    return ports


async def _variant(name: str) -> str:
    async with db.sessionmaker()() as s:
        v = m.Variant(canonical_key=f"bmw|5 series|g30|{name}|ice|pf-{db.uid()}", make="BMW", model="5 Series",
                      generation="G30", variant_name=name, powertrain="ICE", body_class="SEDAN",
                      generation_years_from=2017, generation_years_to=2023)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


async def _asked(vid: str, area: str, chats: int, days_ago: float = 1) -> None:
    at = datetime.now(UTC) - timedelta(days=days_ago)
    async with db.sessionmaker()() as s:
        for _ in range(chats):
            s.add(m.ResearchJob(chat_id=db.uid(), turn_id=db.uid(), variant_id=vid, area=area, status="DONE",
                                started_at=at, finished_at=at))  # fmt: skip
        await s.commit()


async def _fresh(vid: str, area: str) -> None:
    async with db.sessionmaker()() as s:
        s.add(m.ResearchRun(variant_id=vid, area=area, completed_at=datetime.now(UTC), docs_used=3,
                            claims_accepted=20, minimum_met=True))  # fmt: skip
        await s.commit()


async def _purge(vids: list[str]) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.ResearchJob).where(m.ResearchJob.variant_id.in_(vids)))
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.PageRelevance, m.RegistryAttempt):
            await s.execute(delete(t).where(t.variant_id.in_(vids)))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id.in_(vids)))
        await s.execute(delete(m.Variant).where(m.Variant.id.in_(vids)))
        await s.commit()


@pytest.fixture
async def world():
    """Only the cars of this test are asked: research_jobs of other tests would compete for the popular slots."""
    await db.init_db()
    async with sessionmaker()() as s:
        await s.execute(text("DELETE FROM acq_tasks"))
        await s.execute(text("DELETE FROM research_jobs"))
        await s.commit()
    vids: list[str] = []
    yield vids
    await _purge(vids)


def _cfg(**pf):
    cfg = worker_config()
    cfg["worker"] = {**cfg["worker"], "poll_s": 0.05, "lease_s": 30, "metrics_port": 0}
    cfg["prefetch"] = {**cfg["prefetch"], "enabled": True, **pf}
    return cfg


async def _run(cfg: dict, fx: FixtureSearch) -> dict:
    """One prefetch task through the worker (journal, spend, current job = the task id)."""
    ports = _ports(fx)

    async def handler(task, ctx):  # noqa: ANN001, ANN202
        return await prefetch.run(task, ctx, ports=ports)

    tid = await queue.enqueue("prefetch", {}, dedupe_key=f"prefetch:{uuid.uuid4()}", priority=0)
    w = Worker(cfg, handlers={**HANDLERS, "prefetch": handler}, kinds=["prefetch"])
    await w.drain()
    async with sessionmaker()() as s:
        row = (await s.execute(text("SELECT * FROM acq_tasks WHERE id = :i"), {"i": tid})).mappings().one()
    return dict(row)


def _counter(name: str, **labels: str) -> float:
    for metric in exporter.REGISTRY.collect():
        for s in metric.samples:
            if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
                return float(s.value)
    return 0.0


async def test_popular_variant_is_refreshed_before_users_ask(world):
    bmw = await _variant("520d 190 CV")
    rare = await _variant("530i 252 CV")  # fresh: nothing to do
    world += [bmw, rare]
    await _asked(bmw, "specs", chats=2)
    await _asked(rare, "specs", chats=1)
    await _fresh(rare, "specs")
    await _asked(bmw, "specs", chats=3, days_ago=45)  # outside the 30-day window: not counted
    before_v = _counter("automind_prefetch_variants_total")
    before_a = _counter("automind_prefetch_areas_total", area="specs")

    fx = FixtureSearch("bmw520")
    row = await _run(_cfg(), fx)

    assert row["state"] == "done", row["last_error"]
    r = row["result"]
    assert r["jobs"] == 1 and r["variants"] == 1 and r["stopped"] is None
    assert r["by_area"]["specs"]["jobs"] == 1 and r["by_area"]["specs"]["accepted"] == 16
    assert r["refreshed"] == [{"variant_id": bmw, "area": "specs", "accepted": 16, "minimum_met": False}]
    assert fx.queries == ["BMW 5 Series G30 520d 190 CV site:bmw.es OR site:km77.com"]  # the rare car: no search
    async with db.sessionmaker()() as s:
        run = (await s.execute(select(m.ResearchRun).where(m.ResearchRun.variant_id == bmw))).scalar_one()
    assert run.area == "specs" and run.claims_accepted == 16
    # the spend is on the task (fake model + fixture search), and the registry attempts carry the task id
    assert float(row["cost_eur"]) > 0 and float(row["cost_eur"]) == pytest.approx(r["spent_eur"], abs=1e-4)
    async with db.sessionmaker()() as s:
        jobs = set((await s.execute(select(m.RegistryAttempt.job_id).where(m.RegistryAttempt.variant_id == bmw)))
                   .scalars())  # fmt: skip
    assert jobs == {row["id"]}
    assert _counter("automind_prefetch_variants_total") == before_v + 1
    assert _counter("automind_prefetch_areas_total", area="specs") == before_a + 1
    assert _counter("automind_prefetch_spend_today_eur") == pytest.approx(r["spent_today_eur"], abs=1e-6)

    # an hour later the area was just researched (short, but retried only after `short_retry_h`): nothing to do
    fx2 = FixtureSearch("bmw520")
    again = await _run(_cfg(), fx2)
    assert again["result"]["jobs"] == 0 and fx2.queries == []


async def test_due_areas_and_order(world):
    """Areas run in the order the chats asked them; a stale area is due, a fresh one is not; at most
    `variants_per_run` cars and `jobs_per_run` jobs."""
    a = await _variant("520d 190 CV")
    b = await _variant("520i 184 CV")
    c = await _variant("530d 286 CV")
    world += [a, b, c]
    await _asked(a, "specs", chats=3)
    await _asked(a, "price", chats=1)
    await _asked(b, "specs", chats=2)
    await _asked(c, "specs", chats=1)
    async with db.sessionmaker()() as s:  # a's price was researched 40 days ago: stale (fresh_price_days = 30)
        s.add(m.ResearchRun(variant_id=a, area="price", completed_at=datetime.now(UTC) - timedelta(days=40),
                            minimum_met=True))  # fmt: skip
        await s.commit()
    plan = await prefetch.plan(_cfg(variants_per_run=2, jobs_per_run=6)["prefetch"])
    assert plan == [(a, "specs"), (a, "price"), (b, "specs")]
    plan = await prefetch.plan(_cfg(variants_per_run=3, jobs_per_run=2)["prefetch"])
    assert plan == [(a, "specs"), (a, "price")]


async def test_stops_at_the_daily_budget(world):
    bmw = await _variant("520d 190 CV")
    other = await _variant("520i 184 CV")
    world += [bmw, other]
    await _asked(bmw, "specs", chats=2)
    await _asked(other, "specs", chats=1)

    # today's prefetch spend already reached the cap: nothing is searched
    async with sessionmaker()() as s:
        await s.execute(
            text("INSERT INTO acq_tasks (id, kind, dedupe_key, payload, state, cost_eur, finished_at, created_at, "
                 "run_at, priority, attempts, max_attempts) VALUES (:i, 'prefetch', :k, '{}', 'done', 0.30, now(), "
                 "now(), now(), 5, 1, 3)"),
            {"i": db.uid(), "k": f"prefetch:spent:{uuid.uuid4()}"},
        )  # fmt: skip
        await s.commit()
    fx = FixtureSearch("bmw520")
    row = await _run(_cfg(eur_per_day=0.30), fx)
    assert row["state"] == "done" and row["result"]["stopped"] == "budget" and row["result"]["jobs"] == 0
    assert fx.queries == [] and float(row["cost_eur"]) == 0

    # a cap that one job's model calls cross: the job stops at the cap, the next car is never started
    async with sessionmaker()() as s:
        await s.execute(text("DELETE FROM acq_tasks"))
        await s.commit()
    fx = FixtureSearch("bmw520")
    cap = 0.005  # a search (0.001) and one fake model call (~0.0037); the second call is refused
    row = await _run(_cfg(eur_per_day=cap, min_eur_per_job=0.0), fx)
    r = row["result"]
    assert r["stopped"] == "budget" and len(fx.queries) == 1
    assert float(row["cost_eur"]) <= cap + 0.004  # at most one model call past the cap
    assert r["remaining_eur"] == pytest.approx(max(0.0, cap - float(row["cost_eur"])), abs=1e-4)


async def test_disabled_flag_is_respected(world):
    bmw = await _variant("520d 190 CV")
    world.append(bmw)
    await _asked(bmw, "specs", chats=2)
    tid = await queue.enqueue("prefetch", {}, dedupe_key=f"prefetch:{uuid.uuid4()}")
    cfg = _cfg()
    cfg["prefetch"]["enabled"] = False
    await Worker(cfg, kinds=["prefetch"]).drain()  # the shipped handler slot
    async with sessionmaker()() as s:
        row = (await s.execute(text("SELECT state, result FROM acq_tasks WHERE id = :i"), {"i": tid})).one()
    assert row.state == "done" and row.result == {"skipped": "disabled"}
    async with db.sessionmaker()() as s:
        assert (await s.execute(select(m.ResearchRun).where(m.ResearchRun.variant_id == bmw))).first() is None


def test_shipped_config_enables_prefetch_hourly_within_the_owner_budget():
    cfg = worker_config()
    assert cfg["prefetch"]["enabled"] is True and cfg["prefetch"]["eur_per_day"] == 0.30
    entry = cfg["schedule"]["prefetch"]
    assert entry.get("enabled", True) is True and entry["hourly"] == [6, 22]
