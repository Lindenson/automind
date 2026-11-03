"""Research flow on fixtures (US2): jobs per car × area, failures isolated, gap round only for
unmet areas, validator for uncertain pages, cache reuse, cost confirmation (FR-013..FR-023, FR-041)."""

import json
import re

import pytest
from sqlalchemy import delete, select

from automind.infrastructure.db import models as m
from automind.infrastructure.db.repositories import MessageRepo
from automind.infrastructure.db.session import sessionmaker
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM, FixedEstimator
from tests.fakes.fixture_search import FixtureSearch
from tests.golden.runner import load, seed  # noqa: F401  (seed helper reused below)

from .conftest import budget_factory, make_ports

MAKE = "FixtureMake"
INTERPRET = {
    "request": "compare",
    "language": "en",
    "persona_evidence": "for a race enthusiast",
    "delta": {
        "set_persona": {"persona": "PERFORMANCE", "source": "INFERRED"},
        "add_cars": [{"request_text": "FixtureMake Racer", "make": MAKE, "model": "Racer", "condition": "NEW"}],
    },
}

SPEC_CLAIMS = {
    "km77": [
        ("max_power", "206", "kW", "Potencia máxima: 206 kW (280 CV)"),
        ("max_torque", "392", "Nm", "Par máximo: 392 Nm"),
        ("curb_mass", "1.480", "kg", "Peso en vacío: 1.480 kg"),
        ("drivetrain", "Tracción delantera", None, "Tracción delantera"),
    ],
    "ultimatespecs": [
        ("max_power", "206", "kW", "Maximum power 280 PS (206 kW)"),
        ("curb_mass", "1480", "kg", "Curb weight 1480 kg"),
    ],
}
REVIEWS = {
    "evo": [
        ("PRO", "handling", "The steering is precise and full of feel."),
        ("CON", "comfort", "The ride is very firm on broken roads."),
        ("PRO", "other", "The engine pulls hard from low revs."),
        ("CON", "quality", "Cabin plastics feel cheap for the price."),
    ],
    "whatcar": [
        ("PRO", "handling", "The handling is sharp and agile."),
        ("CON", "comfort", "The firm ride becomes tiring on long motorway trips."),
        ("CON", "noise", "Road noise is high at speed."),
    ],
}


def extractor(system: str, user: str):
    url = re.search(r'url="([^"]+)"', user).group(1)
    area = re.search(r"Area: (\w+)", user).group(1)
    if "broken" in url:
        raise ConnectionError("source failed")
    if area == "specs":
        key = "km77" if "km77" in url else "ultimatespecs"
        return {
            "is_about_variant": True,
            "claims": [
                {"attribute": a, "raw_value": r, "unit": u, "excerpt": e, "scope": "VARIANT"}
                for a, r, u, e in SPEC_CLAIMS[key]
            ],
        }
    if area == "measured":
        return {
            "is_about_variant": True,
            "claims": [
                {
                    "attribute": "measured_0_100",
                    "raw_value": "6,1",
                    "unit": "s",
                    "excerpt": "Gemessen 0-100 km/h in 6,1 s",
                    "scope": "VARIANT",
                }
            ],
        }
    if area == "reviews":
        key = "evo" if "evo" in url else "whatcar"
        return {
            "is_about_variant": True,
            "items": [
                {"polarity": p, "tag": t, "reviewer": "EXPERT", "text": x, "excerpt": x} for p, t, x in REVIEWS[key]
            ],
        }
    return {"is_about_variant": False, "claims": [], "items": []}


def validator(system: str, user: str):
    claims = re.findall(r"^(\d+)\. (\w+):", user, flags=re.M)
    return {
        "verdicts": [
            {"index": int(i), "verdict": "OTHER_VARIANT" if a == "curb_mass" else "SAME_VARIANT"} for i, a in claims
        ]
    }


async def purge():
    async with sessionmaker()() as s:
        ids = [v for (v,) in (await s.execute(select(m.Variant.id).where(m.Variant.make == MAKE))).all()]
        for t in (
            m.SpecValue,
            m.Claim,
            m.ResearchRun,
            m.ResearchJob,
            m.ReviewItem,
            m.Issue,
            m.ReliabilityStat,
            m.MaintenanceItem,
            m.TcoEstimateRow,
            m.FeasibilityCheck,
            m.PageRelevance,
            m.ValueRetention,
            m.ValueChallenge,
            m.UsedPriceRange,
        ):
            await s.execute(delete(t).where(t.variant_id.in_(ids)))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id.in_(ids)))
        await s.execute(delete(m.Variant).where(m.Variant.id.in_(ids)))
        s.add(
            m.Variant(
                canonical_key="fixturemake|racer|mk1|2.0 turbo|ice",
                make=MAKE,
                model="Racer",
                generation="Mk1",
                variant_name="2.0 Turbo",
                powertrain="ICE",
                generation_years_from=2024,
            )
        )
        await s.commit()


def runner(saver, llm, search, estimator=None):
    ports = make_ports(llm=llm, search=search)
    if estimator is not None:
        ports.estimator = estimator
    return ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo())


def llm_for_research():
    llm = FakeLLM()
    llm.responders["extractor"] = lambda s, u: extractor(s, u)
    llm.responders["validator"] = validator
    return llm


@pytest.fixture
async def fresh_variant(migrated):
    await purge()


async def test_research_flow_jobs_gaps_validator_and_cache(saver, chat_id, fresh_variant):
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    search = FixtureSearch("racer")
    r = await runner(saver, llm, search).run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r.status == "DONE" and r.action == "REPORT", r.reply_text
    jobs = await make_ports().jobs.for_turn(r.turn_id)
    rounds = sorted((j.area, j.round, j.status) for j in jobs)
    assert rounds == [("measured", 0, "DONE"), ("reviews", 0, "DONE"), ("reviews", 1, "DONE"), ("specs", 0, "DONE")]
    assert llm.roles_called().count("validator") == 1
    async with sessionmaker()() as s:
        v = (await s.execute(select(m.Variant).where(m.Variant.make == MAKE))).scalar_one()
        domains = {
            d for (d,) in (await s.execute(select(m.Evidence.domain).where(m.Evidence.variant_id == v.id))).all()
        }
        runs = {
            x.area: x
            for x in (await s.execute(select(m.ResearchRun).where(m.ResearchRun.variant_id == v.id))).scalars()
        }
        reviews = (await s.execute(select(m.ReviewItem).where(m.ReviewItem.variant_id == v.id))).scalars().all()
        rejected = (
            (await s.execute(select(m.Claim.status).where(m.Claim.variant_id == v.id, m.Claim.status != "ACCEPTED")))
            .scalars()
            .all()
        )
    assert "coches.net" not in domains and "broken.example" not in domains
    assert runs["specs"].minimum_met and runs["measured"].minimum_met and runs["reviews"].minimum_met
    assert runs["reviews"].rounds_used == 1 and len(reviews) == 7
    assert rejected == ["REJECTED_OTHER_VARIANT"]  # the validator dropped the uncertain page's curb weight

    # the same request again within freshness: no research, nothing new
    llm2 = FakeLLM().queue("interpreter", INTERPRET).queue("answerer", "Nothing new.")
    r2 = await runner(saver, llm2, FixtureSearch("racer")).run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r2.action == "ANSWER_FROM_CONTEXT" and r2.usage["search_calls"] == 0


async def test_cost_above_threshold_asks_and_skip_runs_no_jobs(saver, chat_id, fresh_variant):
    llm = FakeLLM().queue("interpreter", INTERPRET).queue("reporter", "Report from what exists.")
    rn = runner(saver, llm, FixtureSearch("racer"), FixedEstimator(eur_per_job=0.2))
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.status == "WAITING_CONFIRMATION" and w.confirm["kind"] == "intake"  # spec 005: the card carries the cost
    assert w.confirm["estimate"]["eur"] >= 0.30 and set(w.confirm["estimate"]["areas"]) == {
        "specs",
        "measured",
        "reviews",
    }
    done = await rn.resume(chat_id, {"choice": "skip"})
    assert done.action == "REPORT" and done.usage["search_calls"] == 0
    assert await make_ports().jobs.for_turn(w.turn_id) == []
    assert json.dumps(done.blocks)  # blocks are serializable


async def test_unmet_minimum_is_reported_as_insufficient_data(saver, chat_id, fresh_variant):
    """Standard depth: reviews never reach 5 items from 2 sources → 'insufficient data', never guessed."""
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    search = FixtureSearch("racer")
    search.spec["queries"][2]["results_by_call"] = [search.spec["queries"][2]["results_by_call"][0]]  # no new docs
    r = await runner(saver, llm, search).run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    texts = [b["text"] for b in r.blocks if b.get("type") == "notice"]
    assert any("insufficient data for reviews" in t for t in texts), texts


async def test_declined_research_is_not_offered_again_for_the_same_plan(saver, chat_id, fresh_variant):
    llm = FakeLLM().queue("interpreter", INTERPRET).queue("reporter", "Report from what exists.")
    rn = runner(saver, llm, FixtureSearch("racer"), FixedEstimator(eur_per_job=0.2))
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.confirm["kind"] == "intake"
    await rn.resume(chat_id, {"choice": "skip"})
    llm.queue("interpreter", {"request": "follow_up_question", "language": "en", "delta": {}})
    llm.queue("answerer", "From what exists: ...")
    r = await rn.run_turn(chat_id, "which one is faster?")
    assert r.status == "DONE" and r.action == "ANSWER_FROM_CONTEXT" and r.usage["search_calls"] == 0


async def test_declined_plan_does_not_block_research_for_a_newly_added_car(saver, chat_id, fresh_variant):
    """Regression (live chat 2026-11-02): the research for car#1 was declined earlier; adding car#2 (new to the
    catalog, confirmed in the same turn) must offer the research again for the new, larger plan, not skip it."""
    llm = FakeLLM().queue("interpreter", INTERPRET).queue("reporter", "Report from what exists.")
    rn = runner(saver, llm, FixtureSearch("racer"), FixedEstimator(eur_per_job=0.2))
    w = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert w.confirm["kind"] == "intake"
    await rn.resume(chat_id, {"choice": "skip"})
    add = {"request_text": "FixtureMake Coupe", "make": MAKE, "model": "Coupe", "condition": "NEW"}
    llm.queue("interpreter", {"request": "compare", "language": "en", "delta": {"add_cars": [add]}})
    llm.queue(
        "resolver",
        {
            "make": MAKE,
            "model": "Coupe",
            "generation": "C1",
            "generation_years_from": 2023,
            "generation_years_to": None,
            "variant_name": "2.0 Turbo",
            "powertrain": "ICE",
            "certainty": "exact",
        },
    )
    w2 = await rn.run_turn(chat_id, "compare it with the FixtureMake Coupe")
    # spec 005: the new, larger plan is offered on the card (cars + cost) — never skipped by the earlier refusal
    assert w2.confirm["kind"] == "intake", w2.reply_text
    assert {c["key"] for c in w2.confirm["card"]["cars"]} == {"car#1", "car#2"}
    usage = (await make_ports().turns.get(w2.turn_id)).usage
    assert usage["llm_calls"] >= 2  # interpreter + resolver before the confirmation


async def test_find_missing_data_and_update_the_report(saver, chat_id, fresh_variant):
    """User report 2026-11-02: "почему нет данных по мазде? найди и обнови отчёт" was answered from the cache."""
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rn = runner(saver, llm, FixtureSearch("racer"))
    r = await rn.run_turn(chat_id, "FixtureMake Racer for a race enthusiast")
    assert r.action == "REPORT"
    async with sessionmaker()() as s:  # pretend one area stayed below its minimum
        v = (await s.execute(select(m.Variant).where(m.Variant.make == MAKE))).scalar_one()
        q = select(m.ResearchRun).where(m.ResearchRun.variant_id == v.id, m.ResearchRun.area == "measured")
        run = (await s.execute(q)).scalar_one()
        run.minimum_met = False
        await s.commit()
    llm.queue("interpreter", {"request": "research_more", "language": "ru", "focus_cars": ["car#1"], "delta": {}})
    llm.queue("reporter", "Updated report.")
    r2 = await rn.run_turn(chat_id, "почему нет данных по разгону? найди и обнови отчёт")
    assert r2.status == "DONE" and r2.action == "REPORT", (r2.action, r2.reply_text)
    jobs = await make_ports().jobs.for_turn(r2.turn_id)
    assert {j.area for j in jobs} == {"measured"}  # only the area that was missing, researched again
