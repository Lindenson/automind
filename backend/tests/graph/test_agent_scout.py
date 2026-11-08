"""Spec 011 T108 (closes 010 T065): the scout finds gaps, searches in the market's language within the budgets, adds
new domains as `discovered`, runs the existing admission check (robots for the found page, a terms clause quoted and
verified, classifieds) and settles each as candidate or blocked, journalled with reason and evidence; it learns the
path prefix of accepted pages and the registry's `site:` queries use it. Fake search, fake LLM, fixture pages only
(the fetcher is replaced; no network). Real Postgres."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select

from automind.acquisition.agents import scout
from automind.acquisition.infrastructure.fetch import FetchRefused
from automind.acquisition.registry.infrastructure import terms
from automind.acquisition.registry.infrastructure.wiring import registry_service
from automind.shared.contracts.web import SearchHit
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import models as m
from automind.shared.research_order import search_plan
from tests.fakes.fake_llm import FakeLLM

LONG = " Datos técnicos completos: potencia, par, peso, consumo, dimensiones y maletero." * 20
TERMS_CLAUSE = "Queda prohibida la extracción automatizada de contenidos mediante robots o scrapers."
PAGES: dict[str, tuple[str, str]] = {
    # a good new spec site: readable page, no terms page -> candidate
    "https://fichas-nuevas.example/coches/seat/leon-15-tsi": ("SEAT León 1.5 TSI ficha técnica", LONG),
    "https://fichas-nuevas.example/": ("Fichas nuevas", LONG),
    # classifieds by its title -> blocked
    "https://anuncios-motor.example/seat-leon": ("Anuncios de coches SEAT León", LONG),
    "https://anuncios-motor.example/": ("Anuncios de coches", LONG),
    # the terms forbid automated reading, with a clause that is on the page -> blocked with the quote
    "https://terminos.example/seat-leon": ("SEAT León", LONG),
    "https://terminos.example/": ("Terminos", LONG),
    "https://terminos.example/terms": ("Terms of use", "Condiciones de uso del sitio. " + TERMS_CLAUSE + LONG),
    # the model claims a prohibition with a quote that is not on the page -> not proof -> candidate
    "https://falsa-cita.example/seat-leon": ("SEAT León", LONG),
    "https://falsa-cita.example/": ("Falsa cita", LONG),
    "https://falsa-cita.example/terms": ("Terms of use", "Condiciones generales. Se permite enlazar." + LONG),
    # robots allow the home page but not the page the search found -> blocked (robots per path)
    "https://robots-ruta.example/": ("Robots ruta", LONG),
}
ROBOTS_REFUSED = {"https://robots-ruta.example/privado/seat-leon"}


class FixtureFetcher:
    client = None

    async def fetch(self, url: str) -> Any:
        if url in ROBOTS_REFUSED:
            raise FetchRefused("robots.txt disallows this path")
        if url not in PAGES:
            raise RuntimeError("404")
        title, body = PAGES[url]
        return type("Doc", (), {"title": title, "text": body})()


@dataclass
class FakeSearch:
    hits: dict[str, list[tuple[str, str]]]
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)

    async def search(self, query: str, *, market: str = "ES", area: str | None = None, fresh: bool = False) -> Any:
        self.calls.append((query, market, area))
        rows = self.hits.get(market, [])
        return [SearchHit(url=u, title=t, snippet="", rank=i) for i, (u, t) in enumerate(rows, 1)]


ES_HITS = [
    ("https://www.km77.com/fichas/seat/leon", "SEAT León ficha km77"),  # known source
    ("https://www.wallapop.com/item/seat-leon-123", "SEAT León"),  # deny-listed: never added
    ("https://fichas-nuevas.example/coches/seat/leon-15-tsi", "SEAT León 1.5 TSI ficha técnica"),
    ("https://anuncios-motor.example/seat-leon", "Anuncios SEAT León"),
    ("https://terminos.example/seat-leon", "SEAT León"),
    ("https://falsa-cita.example/seat-leon", "SEAT León"),
    ("https://robots-ruta.example/privado/seat-leon", "SEAT León"),
]


def _terms_reader(system: str, user: str) -> dict[str, Any]:
    if "Se permite enlazar" in user:
        return {"forbids_automated": True, "clause": "Prohibido todo uso automatizado del sitio."}  # not on the page
    if "prohibida la extracción" in user:
        return {"forbids_automated": True, "clause": TERMS_CLAUSE}
    return {"forbids_automated": False, "clause": ""}


def _scout_reword(system: str, user: str) -> dict[str, Any]:
    assert "<untrusted_document" not in user  # query wording only
    if "Market: ES" in user:  # the second answer has an operator: code keeps the template's query
        return {"queries": ["SEAT León Mk4 1.5 TSI 150 ficha técnica potencia par peso",
                            "SEAT León site:coches.net ficha"]}  # fmt: skip
    return {"queries": []}  # a different count: the templates stand


@pytest.fixture
async def world(monkeypatch):
    await db.init_db()
    tag = uuid.uuid4().hex[:8]
    async with db.sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow, m.RegistryRun):
            await s.execute(delete(t))
        await s.execute(delete(m.AcqTask).where(m.AcqTask.kind == "scout"))
        v = db.Variant(canonical_key=f"scout|{tag}", make="SEAT", model="León", generation="Mk4",
                       variant_name="1.5 TSI 150", powertrain="ICE", fuel="petrol")  # fmt: skip
        s.add(v)
        await s.flush()
        for accepted in (0, 0, 0):
            s.add(m.ResearchJob(chat_id=tag, turn_id=tag, variant_id=v.id, area="specs", status="DONE",
                                accepted=accepted, finished_at=m.now()))  # fmt: skip
        s.add(m.SourceRow(domain="km77.com", source_type="SPEC_DATABASE", family="km77.com", markets=["ES"],
                          access="ok"))  # fmt: skip
        await s.flush()
        cap = m.CapabilityRow(domain="km77.com", area="specs", market="ES", status="active",
                              status_since=m.now() - timedelta(days=30))  # fmt: skip
        s.add(cap)
        await s.flush()
        for i, path in enumerate(("fichas/seat/leon/1", "fichas/bmw/serie-3/2", "fichas/audi/a3/3", "precios/x")):
            s.add(m.RegistryAttempt(capability_id=cap.id, url=f"https://www.km77.com/{path}", outcome="accepted",
                                    values=3 + i))  # fmt: skip
        await s.commit()
        vid = v.id
    real_jobs = scout._jobs

    async def our_jobs(days: int) -> list[scout.Job]:  # other tests' research jobs are not this test's gaps
        return [j for j in await real_jobs(days) if j.variant_id == vid]

    monkeypatch.setattr(scout, "_jobs", our_jobs)
    monkeypatch.setattr(terms, "_fetcher", lambda: FixtureFetcher())
    yield vid
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.ResearchJob).where(m.ResearchJob.variant_id == vid))
        await s.execute(delete(m.Variant).where(m.Variant.id == vid))
        await s.commit()


async def _caps() -> dict[str, m.CapabilityRow]:
    async with db.sessionmaker()() as s:
        return {c.domain: c for c in (await s.execute(select(m.CapabilityRow))).scalars()}


async def _journal(author: str | None = None) -> list[m.RegistryChange]:
    async with db.sessionmaker()() as s:
        q = select(m.RegistryChange).order_by(m.RegistryChange.created_at)
        if author:
            q = q.where(m.RegistryChange.author == author)
        return list((await s.execute(q)).scalars())


async def test_scout_discovers_admits_blocks_and_journals(world) -> None:
    search = FakeSearch({"ES": ES_HITS})
    llm = FakeLLM(responders={"terms_reader": _terms_reader, "scout": _scout_reword})
    out = await scout.run(search, llm=llm, task_id="task-1")

    # the gaps: specs on its markets (3 no-data outcomes), km77 the only active source on ES
    assert out["open_gaps"] == 2 and out["gaps"] == 2
    queries_es = [q for q, mk, _ in search.calls if mk == "ES"]
    assert len(queries_es) == 2  # two open templates for specs, under the per-gap cap of 3
    assert queries_es[0] == "SEAT León Mk4 1.5 TSI 150 ficha técnica potencia par peso"  # reworded
    assert "site:" not in queries_es[1] and queries_es[1].startswith("SEAT León Mk4 1.5 TSI 150")  # template stands
    assert {a for _, _, a in search.calls} == {"specs"}
    assert out["per_gap"] == {"specs|ES": 2, "specs|EN": 2}
    scout_calls = [c for c in llm.calls if c.role == "scout"]
    assert scout_calls and all("<untrusted_document" not in c.user for c in scout_calls)  # never sees a page

    caps = await _caps()
    assert "wallapop.com" not in caps  # deny-listed: never added
    status = {d: c.status for d, c in caps.items() if d != "km77.com"}
    assert status == {
        "fichas-nuevas.example": "candidate",
        "falsa-cita.example": "candidate",  # a quote that is not on the terms page is no proof
        "anuncios-motor.example": "blocked",
        "terminos.example": "blocked",
        "robots-ruta.example": "blocked",
    }
    assert out["added"] == 5 and out["candidate"] == 2 and out["blocked"] == 3
    async with db.sessionmaker()() as s:
        src = await s.get(m.SourceRow, "terminos.example")
        assert src.access == "terms_forbid" and src.access_evidence["clause"] == TERMS_CLAUSE
        assert (await s.get(m.SourceRow, "robots-ruta.example")).access == "robots_blocked"
        assert (await s.get(m.SourceRow, "anuncios-motor.example")).access == "classifieds"

    journal = await _journal("scout")
    added = {c.domain: c for c in journal if c.change == "added"}
    assert set(added) == set(status)
    a = added["fichas-nuevas.example"]
    assert a.reason.startswith("scout: gap specs/ES (3 no-data outcomes, 1 active); hit #3 of ")
    assert a.evidence["url"] == "https://fichas-nuevas.example/coches/seat/leon-15-tsi"
    assert a.evidence["task_id"] == "task-1" and a.after == {"status": "discovered", "area": "specs", "market": "ES"}
    settled = {c.domain: c for c in journal if c.change in ("promoted", "blocked")}
    p = settled["fichas-nuevas.example"]
    assert p.before == {"status": "discovered"} and p.after == {"status": "candidate"}
    assert p.evidence["change_id"] == a.id and p.evidence["sample_url"] == a.evidence["url"]
    b = settled["terminos.example"]
    assert b.after == {"status": "blocked"} and b.evidence["admission"]["clause"] == TERMS_CLAUSE
    assert "terms of use forbid" in b.reason

    # the locator: three accepted km77 pages under /fichas/ -> the site: queries name km77.com/fichas
    km = caps["km77.com"]
    assert km.url_patterns == ["/fichas/"] and out["patterns"] == 1
    (loc,) = [c for c in journal if c.change == "url_patterns"]
    assert loc.domain == "km77.com" and loc.after == {"url_patterns": ["/fichas/"]}
    assert "3 of 4 accepted pages" in loc.reason
    cfg = load_yaml("registry.yaml")
    (src,) = [x for x in await registry_service(cfg).sources_for("specs", ["ES"], 10)
              if x.domain == "km77.com"]  # fmt: skip
    assert src.site == "km77.com/fichas"
    car = search_plan.Identity("SEAT", "León", "Mk4", "1.5 TSI 150")
    (q,) = search_plan.registry_queries("specs", car, [(src.site, "ES")], {})
    assert "site:km77.com/fichas" in q.text

    async with db.sessionmaker()() as s:
        (run,) = (await s.execute(select(m.RegistryRun).where(m.RegistryRun.kind == "scout"))).scalars().all()
    assert run.discovery_queries == 4 and run.changes == 5


async def test_scout_stops_at_the_budget_and_the_per_gap_cap(world) -> None:
    search = FakeSearch({"ES": ES_HITS})
    llm = FakeLLM(responders={"terms_reader": _terms_reader})  # no scout output: the templates' wording stands
    reg = {**load_yaml("registry.yaml"), "discovery": {**load_yaml("registry.yaml")["discovery"], "eur_per_day": 0.0}}
    out = await scout.run(search, llm=llm, reg=reg)
    assert out["stopped"] == "budget" and search.calls == [] and out["added"] == 0

    # today's queries for the gap are spent: no search for it, the other gap still gets its share
    out = await scout.run(search, llm=llm, used={"specs|ES": 3})
    assert all(mk != "ES" for _, mk, _ in search.calls)
    assert out["per_gap"] == {"specs|EN": 2}

    # the worker's budget of the kind also stops it (charge raises)
    from automind.acquisition.worker.budget import BudgetExceeded

    async def broke(eur: float) -> None:
        raise BudgetExceeded("scout")

    search.calls.clear()
    out = await scout.run(search, llm=llm, charge=broke)
    assert out["stopped"] == "budget" and search.calls == []


async def test_scout_handler_is_registered_and_scheduled() -> None:
    from automind.acquisition.worker.config import worker_config
    from automind.acquisition.worker.handlers import HANDLERS

    assert "scout" in HANDLERS
    assert worker_config()["schedule"]["scout"]["daily"]
