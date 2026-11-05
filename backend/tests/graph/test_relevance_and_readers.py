"""US1 in a turn (spec 003 T030/T032/T033): wrong-generation pages are rejected before extraction, a
favourite spec site is read without AI, and the case-aware validator drops a value for another market."""

import re
import uuid

import pytest
from sqlalchemy import delete, select

from automind.acquisition.parsing.legacy import Registry
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import MessageRepo
from automind.infrastructure.db.session import sessionmaker
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

from .conftest import budget_factory, engine, make_ports, open_web_reference, share

KM77 = {"domain": "km77.com", "source_type": "SPEC_DATABASE", "areas": ["specs"], "markets": ["ES"], "priority": 1,
        "reader": "km77", "tos_checked": "2026-11-02"}  # fmt: skip
INTERPRET = {
    "request": "single",
    "language": "en",
    "persona_evidence": "for a race enthusiast",
    "delta": {
        "set_persona": {"persona": "PERFORMANCE", "source": "INFERRED"},
        "add_cars": [
            {
                "request_text": "BMW 520d G30",
                "make": "BMW",
                "model": "5 Series",
                "condition": "NEW",
                "constraints": {"generation_hint": "G30", "trim_hint": "520d"},
            }
        ],
    },
}


async def _seed():
    async with sessionmaker()() as s:
        ids = [v for (v,) in (await s.execute(select(m.Variant.id).where(m.Variant.make == "BMW"))).all()]
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.ResearchJob, m.ReviewItem, m.Issue, m.ReliabilityStat,
                  m.MaintenanceItem, m.TcoEstimateRow, m.PageRelevance, m.UsedPriceRange):  # fmt: skip
            await s.execute(delete(t).where(t.variant_id.in_(ids)))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id.in_(ids)))
        await s.execute(delete(m.Variant).where(m.Variant.id.in_(ids)))
        s.add(
            m.Variant(
                canonical_key="bmw|5 series|g30|520d 190 cv|ice", make="BMW", model="5 Series", generation="G30",
                variant_name="520d 190 CV", powertrain="ICE", body_class="SEDAN", generation_years_from=2017,
                generation_years_to=2023,
            )
        )  # fmt: skip
        await s.commit()


def extractor(system, user):
    url = re.search(r'url="([^"]+)"', user).group(1)
    assert "km77.com" not in url, "km77 is read by the site reader, not by the LLM"
    assert "g60" not in url, "the G60 page must be rejected before extraction"
    return {"is_about_variant": True, "claims": [
        {"attribute": "max_power", "raw_value": "190", "unit": "hp", "excerpt": "Maximum power 190 hp (140 kW)",
         "scope": "VARIANT"}]}  # fmt: skip


def validator(system, user):
    assert "market ES" in user
    return {"verdicts": [{"index": 0, "verdict": "OTHER_MARKET", "reason": "UK rating"}]}


@pytest.mark.usefixtures("migrated")
async def test_gate_reader_and_market_validator(saver):
    await _seed()
    llm = FakeLLM().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    llm.responders["extractor"] = extractor
    llm.responders["validator"] = validator
    fx = FixtureSearch("bmw520")
    ports = make_ports(llm=llm, search=fx)
    share(ports, ref=open_web_reference(
        favourites=[KM77], favourite_queries={"specs": "{make} {model} {generation} {variant} {sites}"}
    ))  # fmt: skip
    engine(ports).readers = Registry(load_yaml("site_readers.yaml"), [KM77])
    r = await ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo()).run_turn(
        str(uuid.uuid4()), "BMW 520d G30 for a race enthusiast"
    )
    assert r.status == "DONE", r.reply_text
    async with sessionmaker()() as s:
        v = (await s.execute(select(m.Variant).where(m.Variant.make == "BMW"))).scalar_one()
        claims = (await s.execute(select(m.Claim).where(m.Claim.variant_id == v.id))).scalars().all()
        q_power = select(m.SpecValue).where(m.SpecValue.variant_id == v.id, m.SpecValue.attribute == "max_power")
        power = (await s.execute(q_power)).scalar_one()
        q_job = select(m.ResearchJob).where(
            m.ResearchJob.variant_id == v.id, m.ResearchJob.area == "specs", m.ResearchJob.round == 0
        )
        job = (await s.execute(q_job)).scalar_one()
    reader = [c for c in claims if c.extracted_by == "READER"]
    assert {c.attribute for c in reader} >= {"max_power", "max_torque", "curb_mass", "claimed_0_100", "top_speed"}
    assert all(c.status == "ACCEPTED" for c in reader if c.attribute in ("max_power", "curb_mass"))
    llm_claims = [c for c in claims if c.extracted_by == "LLM"]
    assert [c.status for c in llm_claims] == ["REJECTED_OTHER_MARKET"]
    assert power.value_num == 140
    assert job.pages_rejected == {"other_variant": 1} and job.reader_values >= 5
    assert job.values_rejected.get("other_market") == 1
    assert llm.roles_called().count("validator") == 1
