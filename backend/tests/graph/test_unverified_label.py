"""Spec 011 T121/T122 (closes 010 T059): a value whose only sources are registry candidates is labelled "unverified
source" in the report and each such source counts as half an independent source towards the area's minimum."""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from sqlalchemy import delete, select

from automind.acquisition.pipeline import job as research
from automind.acquisition.pipeline.job import JobSpec
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.chat.application.services.report.blocks.sources import sources_block
from automind.chat.application.services.report.blocks.spec_table import spec_table
from automind.chat.application.services.report.facts.car import load_car
from automind.shared.infrastructure.config.loader import favourite_queries, load_yaml
from automind.shared.infrastructure.db import models as m
from automind.shared.infrastructure.db.session import sessionmaker
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import engine, make_ports, open_web_reference

CANDIDATES = ("cand-a.example", "cand-b.example")
REGISTRY_TABLES = (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow)


async def clear_registry() -> None:
    async with sessionmaker()() as s:
        for t in REGISTRY_TABLES:
            await s.execute(delete(t))
        await s.commit()


@pytest.fixture
async def registry_rows(migrated):
    """The test's own registry rows; removed afterwards so later tests do not query these candidates."""
    await clear_registry()
    yield
    await clear_registry()


async def _setup() -> str:
    async with sessionmaker()() as s:
        for dom in CANDIDATES:
            s.add(m.SourceRow(domain=dom, source_type="SPEC_DATABASE", family=dom, markets=["ES"], access="ok"))
            await s.flush()
            s.add(m.CapabilityRow(domain=dom, area="specs", market="ES", status="candidate"))
        v = m.Variant(canonical_key=f"candmake|roadster|r1|{uuid.uuid4().hex}", make="CandMake", model="Roadster",
                      generation="R1", variant_name="2.0 T 190", powertrain="ICE", generation_years_from=2019,
                      generation_years_to=2024)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


def _extractor(system: str, user: str) -> dict:
    excerpt = "Potencia máxima: 190 CV" if "cand-a.example" in user else "rinde 190 CV"
    claim = {"attribute": "max_power", "raw_value": "190", "unit": "CV", "excerpt": excerpt, "scope": "VARIANT"}
    return {"is_about_variant": True, "claims": [claim]}


def ports_for(scenario: str):  # noqa: ANN201
    llm = FakeLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["relevance"] = lambda s, u: {"verdict": "RELEVANT", "reason": "the car"}
    search = FixtureSearch(scenario)
    ports = engine(make_ports(llm=llm, search=search))
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}
    ports.registry = RegistryService(RegistryRepo(cfg), cfg)
    ref = open_web_reference(
        favourite_queries={k: v for k, v in favourite_queries().items() if k.startswith("registry")}
    )
    # one candidate per `site:` query, so each fixture query names one domain
    ports.ref = dataclasses.replace(ref, registry={**(ref.registry or {}), "site_query_domains_per_query": 1})
    return ports, search


async def _emit(stage: str, text: str) -> None:
    return None


async def test_candidate_values_are_labelled_and_count_half(registry_rows):
    vid = await _setup()
    ports, search = ports_for("unverified")
    res = await research.run_job(ports, JobSpec(str(uuid.uuid4()), vid, "specs", round=0), _emit)
    assert res.ok, res.error
    assert sorted(q for q in search.queries if "site:" in q) == [
        "CandMake Roadster 2.0 190 site:cand-a.example",
        "CandMake Roadster 2.0 190 site:cand-b.example",
    ], search.queries
    assert res.accepted == 2
    # two independent non-manufacturer domains would meet the specs minimum; two candidates are 0.5 + 0.5
    assert sorted(h["domain"] for h in res.hits) == list(CANDIDATES)
    assert all(h["unverified"] for h in res.hits)
    assert not res.minimum_met
    async with sessionmaker()() as s:
        flags = (await s.execute(select(m.Evidence.unverified).where(m.Evidence.variant_id == vid))).scalars().all()
        run = (await s.execute(select(m.ResearchRun).where(m.ResearchRun.variant_id == vid))).scalar_one()
    assert flags and all(flags)
    assert run.minimum_met is False

    # the report: every source of the value carries the label
    car = await load_car(vid)
    table = spec_table([car], {vid: False})
    (row,) = [r for r in table["rows"] if r["key"] == "max_power"]
    (cell,) = row["values"]
    assert cell["available"] and cell["sources"]
    assert all(src["unverified"] is True for src in cell["sources"])
    items = sources_block([car])["items"]
    assert {i["url"] for i in items if i.get("unverified")} == {i["url"] for i in items}
