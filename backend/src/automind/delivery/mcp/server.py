"""AutoMind MCP server: deterministic tools for analyst agents (no LLM inside; contracts/rest-and-mcp.md).

Run: python -m automind.delivery.mcp.server   (stdio transport)
Tools only read validated data from the database and compute; they never fetch the web and never
start research (constitution VIII). Every result carries units and provenance/basis labels;
scores are labelled as 0–100 indices, metrics as measurements derived from sourced values.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from sqlalchemy import select

from automind.chat.application.services.report import compose
from automind.chat.domain.assessment import dragrace
from automind.chat.domain.assessment.criteria import CriteriaModel, score, weights_for
from automind.chat.domain.assessment.metrics import metrics
from automind.chat.domain.case.casefile import CaseFile
from automind.chat.domain.cost import tco
from automind.chat.infrastructure.persistence.repositories import CaseRepo
from automind.shared.infrastructure import db
from automind.shared.infrastructure.config.loader import configure_domain, load_yaml
from automind.shared.infrastructure.config.loader import rates as rates_config

configure_domain()
mcp = FastMCP("automind")
MODEL = CriteriaModel.from_config(load_yaml("criteria.yaml"), load_yaml("profile_rules.yaml"))
SCORE_NOTE = "0–100 indices (scores), not measurements"


async def _cars(car_ids: list[str]) -> list[dict[str, Any]]:
    return [await compose.load_car(cid) for cid in car_ids]


async def _case(chat_id: str) -> CaseFile:
    _, data, _ = await CaseRepo().latest(chat_id)
    return CaseFile.model_validate(data) if data else CaseFile()


@mcp.tool()
async def get_case(chat_id: str) -> dict[str, Any]:
    """The chat's case file (read-only): persona, cars (car_id = variant_id), priorities, weights, usage."""
    c = await _case(chat_id)
    return {
        "persona": c.persona,
        "cars": [
            {"key": x.key, "car_id": x.variant_id, "label": x.label, "condition": x.condition, "year": x.year}
            for x in c.cars
        ],
        "priorities": [p.model_dump() for p in c.priorities],
        "weights": weights_for(c, MODEL),
        "usage": c.usage,
        "budget_eur": c.budget.max_eur,
        "annual_km": c.annual_km,
        "unmapped_wishes": c.unmapped_wishes,
    }


@mcp.tool()
async def list_catalog(query: str = "") -> list[dict[str, Any]]:
    """Variants in the validated local catalog (optionally filtered by text), with generation years."""
    async with db.sessionmaker()() as s:
        vs = list((await s.execute(select(db.Variant))).scalars())
    q = query.lower()
    return [
        {"car_id": v.id, "label": v.label, "generation_years": [v.generation_years_from, v.generation_years_to]}
        for v in vs
        if q in v.label.lower()
    ]


@mcp.tool()
async def get_vehicle_specs(car_id: str, tier: int | None = None) -> dict[str, Any]:
    """Validated specifications with provenance, confidence and number of sources (optionally one tier).
    Missing values are listed under 'unavailable' and must not be guessed."""
    car = await compose.load_car(car_id)
    out, missing = {}, []
    for k, attr in compose.specs.ATTRS.items():
        if tier is not None and attr.tier != tier:
            continue
        sv = car["values"].get(k)
        if sv is None or not sv.available:
            missing.append(k)
            continue
        out[k] = {
            "value": compose.display(k, sv),
            "provenance": sv.provenance,
            "confidence": sv.confidence,
            "sources": len(sv.claim_ids),
            "conflict_alternatives": sv.alternatives,
        }
    return {"car_id": car_id, "label": car["variant"].label, "specs": out, "unavailable": missing}


@mcp.tool()
async def compute_metrics(car_ids: list[str]) -> list[dict[str, Any]]:
    """Derived METRICS with units (not scores): power_to_weight kW/t, weight_to_power kg/kW,
    torque_to_weight N·m/t, specific_output kW/L. Basis: DERIVED from sourced values."""
    return [
        {"car_id": c["variant"].id, "label": c["variant"].label, "basis": "DERIVED", **metrics(compose.facts(c))}
        for c in await _cars(car_ids)
    ]


@mcp.tool()
async def score_criteria(
    chat_id: str, car_ids: list[str] | None = None, weights: dict[str, float] | None = None
) -> dict[str, Any]:
    """Criteria SCORES (0–100 indices, not measurements) for the chat's cars with the case weights
    (or the given weights), with coverage, insufficient flags and the inputs used per criterion."""
    case = await _case(chat_id)
    ids = car_ids or [x.variant_id for x in case.cars if x.variant_id]
    cars = await _cars([i for i in ids if i])
    race = compose.run_race(cars, case.race_settings.model_dump() if case.race_settings else None)
    sims = {r.car_id: r for r in race.results}
    ctx = {x.variant_id: x for x in case.cars}
    facts = [
        compose.facts(
            c,
            sims.get(c["variant"].id),
            condition=getattr(ctx.get(c["variant"].id), "condition", "NEW"),
            age_years=getattr(ctx.get(c["variant"].id), "age_years", None),
        )
        for c in cars
    ]
    w = weights or weights_for(case, MODEL)
    block = compose.criteria_block(score(facts, w, MODEL), MODEL, case.unmapped_wishes)
    return {"note": SCORE_NOTE, **block}


@mcp.tool()
async def simulate_drag_race(
    car_ids: list[str],
    surface: Literal["DRY", "WET"] = "DRY",
    extra_load_kg: float = 0,
    temperature_c: float = 20,
    altitude_m: float = 0,
) -> dict[str, Any]:
    """Deterministic drag race simulation. Results are SIMULATED_ESTIMATE with model version and assumptions."""
    race = dragrace.simulate(
        [compose.race_inputs(c) for c in await _cars(car_ids)],
        dragrace.RaceSettings(surface, extra_load_kg, temperature_c, altitude_m),
    )
    return {
        "provenance": "SIMULATED_ESTIMATE",
        "model_version": race.model_version,
        "results": [
            {
                "car_id": r.car_id,
                "label": r.label,
                "rank": r.rank,
                "t_0_100_s": r.t_0_100,
                "t_0_200_s": r.t_0_200,
                "t_400m_s": r.t_400m,
                "v_400m_kmh": r.v_400m,
                "claimed_0_100_s": r.claimed_0_100,
                "assumptions": r.assumptions,
            }
            for r in race.results
        ],
        "excluded": race.excluded,
    }


@mcp.tool()
async def compute_tco(
    chat_id: str, car_ids: list[str] | None = None, annual_km: int | None = None
) -> list[dict[str, Any]]:
    """Ownership cost per car (EUR/year). Every item is labelled SOURCED or ASSUMPTION with its inputs."""
    case = await _case(chat_id)
    ids = car_ids or [x.variant_id for x in case.cars if x.variant_id]
    rates = tco.TcoRates.from_config(rates_config(), case.rates_override.model_dump())
    ctx = {x.variant_id: x for x in case.cars}
    out = []
    for c in await _cars([i for i in ids if i]):
        x = ctx.get(c["variant"].id)
        car = await compose.tco_car(
            c, getattr(x, "condition", "NEW"), getattr(x, "age_years", None), getattr(x, "mileage_km", None)
        )
        est = tco.compute(car, rates, annual_km or case.annual_km)
        out.append(compose.tco_block([est])["cars"][0])
    return out


@mcp.tool()
async def get_reliability(car_id: str) -> dict[str, Any]:
    """Documented technical issues (component, recurrence by source count) and reliability statistics."""
    car = await compose.load_car(car_id)
    s = compose.reliability_summary(car)
    return {
        "car_id": car_id,
        "label": car["variant"].label,
        "minimum_met": bool(s and s.minimum_met),
        "summary": s.__dict__ if s else None,
        "issues": [
            {
                "component": i.component,
                "description": i.description,
                "source": e.domain,
                "age_window": [i.age_from, i.age_to],
            }
            for i, e in car["issues"]
        ],
    }


@mcp.tool()
async def get_reviews(car_id: str) -> dict[str, Any]:
    """Validated review points (pros/cons by tag) with recurring vs isolated and the review minimum."""
    car = await compose.load_car(car_id)
    s = compose.review_summary(car)
    return {
        "car_id": car_id,
        "label": car["variant"].label,
        "minimum_met": bool(s and s.minimum_met),
        "recurring": s.recurring if s else {},
        "isolated": s.isolated if s else {},
        "points": [
            {"polarity": r.polarity, "tag": r.tag, "text": r.text, "source": e.domain} for r, e in car["reviews"]
        ],
    }


@mcp.tool()
async def get_engineering(car_id: str) -> dict[str, Any]:
    """Tier 2 engineering items with confidence and sources."""
    car = await compose.load_car(car_id)
    block = compose.engineering_block([car])
    return {"car_id": car_id, "label": car["variant"].label, "items": block["cars"][0]["items"] if block else []}


@mcp.tool()
async def get_manufacturer(make: str) -> dict[str, Any]:
    """Sourced manufacturer facts (history, key models, market position)."""
    async with db.sessionmaker()() as s:
        rows = (await s.execute(select(db.ManufacturerFact).where(db.ManufacturerFact.make == make))).scalars()
        return {
            "make": make,
            "facts": [
                {"kind": f.fact_type, "text": f.text, "positioning": f.positioning, "source": f.url} for f in rows
            ],
        }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
