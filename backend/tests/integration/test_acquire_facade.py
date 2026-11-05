"""The acquisition facade (spec 011 T038, contracts/acquire.md): `acquire()` gives the same result as the research job
it replaced, lists the domains it tried, and `Need.CACHED` never searches."""

import pytest
from sqlalchemy import delete, select
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.graph.conftest import make_ports, open_web_reference

from automind.acquisition import api as acquisition
from automind.acquisition.parsing.legacy import Registry
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.infrastructure import db
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db import models as m

KM77 = {"domain": "km77.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 1,
        "reader": "km77", "tos_checked": "2026-11-02"}  # fmt: skip

# recorded from `application.research.run_job` before the strangler moved it (spec 011 T038)
EXPECTED = {"docs": 2, "accepted": 16, "rejected": 1, "minimum_met": False}
EXPECTED_HITS = [{"domain": "km77.com", "source_type": "SPEC_DATABASE", "items": 16}]


def _extractor(system, user):  # noqa: ANN001
    claim = {"attribute": "max_power", "raw_value": "190", "unit": "CV", "excerpt": "190 CV", "scope": "VARIANT"}
    return {"is_about_variant": True, "claims": [claim]}


async def _bmw() -> str:
    async with db.sessionmaker()() as s:
        v = m.Variant(canonical_key=f"bmw|5 series|g30|520d 190 cv|ice|acq-{db.uid()}", make="BMW", model="5 Series",
                      generation="G30", variant_name="520d 190 CV", powertrain="ICE", body_class="SEDAN",
                      generation_years_from=2017, generation_years_to=2023)  # fmt: skip
        s.add(v)
        await s.commit()
        return v.id


async def _purge(vid: str) -> None:
    async with db.sessionmaker()() as s:
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.PageRelevance, m.RegistryAttempt):
            await s.execute(delete(t).where(t.variant_id == vid))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id == vid))
        await s.execute(delete(m.Variant).where(m.Variant.id == vid))
        await s.commit()


def _ports(fx: FixtureSearch):  # noqa: ANN202
    llm = FakeLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["validator"] = lambda s, u: {"verdicts": [{"index": 0, "verdict": "OTHER_MARKET"}]}
    ports = make_ports(llm=llm, search=fx)
    ports.ref = open_web_reference(
        favourites=[KM77], favourite_queries={"specs": "{make} {model} {generation} {variant} {sites}"}
    )
    ports.readers = Registry(load_yaml("site_readers.yaml"), [KM77])
    cfg = {**load_yaml("registry.yaml"), "autonomy": False}
    ports.registry = RegistryService(RegistryRepo(cfg), cfg)
    return ports


@pytest.fixture
async def bmw():
    await db.init_db()
    vid = await _bmw()
    yield vid
    await _purge(vid)


async def test_acquire_equals_the_research_job_and_lists_what_it_tried(bmw):
    fx = FixtureSearch("bmw520")
    stages: list[str] = []

    async def emit(stage: str, text: str) -> None:
        stages.append(stage)

    req = acquisition.AcquireRequest(job_id=db.uid(), variant_id=bmw, kinds=["specs"])
    res = await acquisition.acquire(req, emit, ports=_ports(fx))
    (k,) = res.kinds
    assert k.ok, k.error
    assert {"docs": k.docs, "accepted": k.accepted, "rejected": k.rejected, "minimum_met": k.minimum_met} == EXPECTED
    assert k.hits == EXPECTED_HITS
    # km77 gave values (its G60 page was another variant); the US page was another market
    assert {t.domain: t.outcome for t in k.tried} == {"km77.com": "accepted", "example-specs.com": "rejected"}
    assert fx.queries == ["BMW 5 Series G30 520d 190 CV site:bmw.es OR site:km77.com"]
    assert "searching" in stages and "validating" in stages
    # spec 011 FR-002: the versions of the stages that ran, on the result, every attempt and the research run
    assert k.stage_versions["plan"] == "plan@1" and k.stage_versions["merge"] == "merge@1"
    async with db.sessionmaker()() as s:
        runs = (await s.execute(select(m.ResearchRun.stage_versions).where(m.ResearchRun.variant_id == bmw))).scalars()
        attempts = (
            await s.execute(select(m.RegistryAttempt.stage_versions).where(m.RegistryAttempt.job_id == req.job_id))
        ).scalars()
        assert [r for r in runs] == [k.stage_versions]
        assert all(a == k.stage_versions for a in attempts)


async def test_cached_need_never_searches(bmw):
    fx = FixtureSearch("bmw520")
    req = acquisition.AcquireRequest(job_id=db.uid(), variant_id=bmw, kinds=["specs"], need=acquisition.Need.CACHED)
    res = await acquisition.acquire(req, None, ports=_ports(fx))
    assert fx.queries == [] and fx.extracted == []
    (k,) = res.kinds
    assert k.ok and k.docs == 0 and k.hits == [] and not k.minimum_met


async def test_the_chat_interface_imports_no_engine():
    import subprocess
    import sys

    code = ("import sys, automind.acquisition.api; "
            "bad = [m for m in sys.modules if m.startswith(('automind.acquisition.', 'automind.infrastructure', "
            "'sqlalchemy')) and m != 'automind.acquisition.api']; print(bad); sys.exit(1 if bad else 0)")  # fmt: skip
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
