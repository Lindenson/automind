"""Live chat 5821ac77: the registry's sources are queried (`site:`), not only the configured favourites. A used-price
area below its minimum after round 0 escalates to the registry's sources of the other European markets; a surveyed
candidate's page is read, its attempt recorded, and a whole-generation range is not taken for the car's year."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, select

from automind.acquisition.pipeline import job as research
from automind.acquisition.pipeline.job import JobSpec
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure.config import favourite_queries, load_yaml
from automind.infrastructure.db import models as m
from automind.infrastructure.db.session import sessionmaker
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import make_ports, open_web_reference


async def _setup() -> str:
    async with sessionmaker()() as s:
        for t in (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow):
            await s.execute(delete(t))
        for dom, access, status, market in (
            ("valuer.example", "ok", "candidate", "FR"),  # surveyed candidate of another European market
            ("forbidden.example", "terms_forbid", "candidate", "FR"),  # terms forbid: never queried
            ("home.example", "ok", "candidate", "ES"),  # the area's own market: round 0, not the follow-up
            ("faraway.example", "ok", "candidate", "JP"),  # prices come from Europe only
        ):
            s.add(m.SourceRow(domain=dom, source_type="PUBLICATION", family=dom, markets=[market], access=access))
            await s.flush()
            s.add(m.CapabilityRow(domain=dom, area="used_price", market=market, status=status))
        v = m.Variant(canonical_key=f"regmake|cruiser|j1|{uuid.uuid4().hex}", make="RegMake", model="Cruiser",
                      generation="J1", variant_name="3.0 D 190", powertrain="ICE", generation_years_from=2009,
                      generation_years_to=2023)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


def _extractor(system: str, user: str) -> dict:
    assert re.search(r'url="https://www.valuer.example/', user), user[:200]
    return {
        "is_about_variant": True,
        "ranges": [
            {"model_year_from": 2016, "model_year_to": 2016, "min": 30000, "max": 34000,
             "excerpt": "de 2016 : entre 30.000 et 34.000 euros"},
            {"model_year_from": 2009, "model_year_to": 2023, "min": 12000, "max": 18000,
             "excerpt": "se négocie entre 12.000 et 18.000 euros"},
        ],
    }  # fmt: skip


async def test_follow_up_round_queries_registry_candidates_of_other_european_markets(migrated):
    vid = await _setup()
    llm = FakeLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["relevance"] = lambda s, u: {"verdict": "RELEVANT", "reason": "the car"}
    search = FixtureSearch("registry")
    ports = make_ports(llm=llm, search=search)
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}  # querying does not need autonomy
    ports.registry = RegistryService(RegistryRepo(cfg), cfg)
    ports.ref = open_web_reference(  # open web as in every fixture scenario, plus the registry query templates
        favourite_queries={k: v for k, v in favourite_queries().items() if k.startswith("registry")}
    )

    async def emit(stage: str, text: str) -> None:
        return None

    job = JobSpec(str(uuid.uuid4()), vid, "used_price", round=1, car_year=2016)
    res = await research.run_job(ports, job, emit)
    assert res.ok, res.error
    site = [q for q in search.queries if "site:" in q]
    assert site == ["RegMake Cruiser 2016 site:valuer.example"], search.queries
    assert search.markets[search.queries.index(site[0])] == "FR"
    assert "https://www.valuer.example/regmake/cruiser/2016" in search.extracted
    assert res.accepted == 1 and res.minimum_met
    async with sessionmaker()() as s:
        ranges = (await s.execute(select(m.UsedPriceRange).where(m.UsedPriceRange.variant_id == vid))).scalars().all()
        attempts = (
            await s.execute(
                select(m.CapabilityRow.domain, m.CapabilityRow.market, m.RegistryAttempt.outcome).join(
                    m.CapabilityRow, m.CapabilityRow.id == m.RegistryAttempt.capability_id
                )
            )
        ).all()
        cap = (await s.execute(select(m.CapabilityRow).where(m.CapabilityRow.domain == "valuer.example"))).scalar_one()
    assert sorted((r.model_year_from, r.model_year_to, r.status) for r in ranges) == [
        (2009, 2023, "REJECTED_OTHER_YEAR"),
        (2016, 2016, "ACCEPTED"),
    ]
    assert attempts == [("valuer.example", "FR", "accepted")]
    assert cap.status == "candidate" and cap.attempts == 1  # an attempt is recorded, the status is untouched

    # round 0 of the same area: the area's own market's candidate, not the other markets'
    search0 = FixtureSearch("registry")
    ports.search = search0
    await research.run_job(ports, JobSpec(str(uuid.uuid4()), vid, "used_price", round=0, car_year=2016), emit)
    assert [q for q in search0.queries if "site:" in q and "example" in q] == ["RegMake Cruiser 2016 site:home.example"]
