"""Deterministic analysis: load cached data, compute metrics/race/scores/costs, build UI blocks.

Used both by deterministic graph nodes and by the MCP server tools (same functions, same results).
"""

from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

from sqlalchemy import select

from automind.domain import dragrace, reliability, reviews, specs, tco, units
from automind.domain import evidence as evidence_rules
from automind.domain import metrics as scoring  # noqa: F401 (CarFacts, metrics, ownership)
from automind.domain.criteria import CriteriaModel, CriteriaScore
from automind.domain.metrics import ReliabilitySummary, ReviewSummary
from automind.infrastructure import db

TABLE_ROWS = [
    "engine",
    "max_power",
    "max_torque",
    "curb_mass",
    "drivetrain",
    "transmission",
    "displacement",
    "battery_kwh",
    "claimed_0_100",
    "top_speed",
    "consumption",
    "boot_volume",
    "seats",
    "official_price_es",
    "service_interval_km",
    "service_interval_months",
]


async def load_car(variant_id: str) -> dict:
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        if v is None:
            raise KeyError(f"unknown variant {variant_id}")
        values = {
            sv.attribute: sv
            for sv in (await s.execute(select(db.SpecValue).where(db.SpecValue.variant_id == variant_id))).scalars()
        }
        rows = (
            await s.execute(
                select(db.Claim, db.Evidence)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .where(db.Claim.variant_id == variant_id, db.Claim.status == "ACCEPTED")
            )
        ).all()
        runs = list((await s.execute(select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id))).scalars())
        issues = (
            await s.execute(
                select(db.Issue, db.Evidence)
                .join(db.Evidence, db.Issue.evidence_id == db.Evidence.id)
                .where(db.Issue.variant_id == variant_id)
            )
        ).all()
        reviews = (
            await s.execute(
                select(db.ReviewItem, db.Evidence)
                .join(db.Evidence, db.ReviewItem.evidence_id == db.Evidence.id)
                .where(db.ReviewItem.variant_id == variant_id)
            )
        ).all()
        stats = list(
            (await s.execute(select(db.ReliabilityStat).where(db.ReliabilityStat.variant_id == variant_id))).scalars()
        )
        facts_rows = list(
            (await s.execute(select(db.ManufacturerFact).where(db.ManufacturerFact.make == v.make))).scalars()
        )
        rejected_rows = (
            await s.execute(
                select(db.PageRelevance, db.Document)
                .join(db.Document, db.PageRelevance.document_id == db.Document.id)
                .where(
                    db.PageRelevance.variant_id == variant_id,
                    db.PageRelevance.verdict.in_(("OTHER_VARIANT", "NOT_ABOUT_CAR")),
                )
                .order_by(db.PageRelevance.created_at.desc())
                .limit(20)
            )
        ).all()
    rejected_pages = [
        {
            "name": (d.title or d.url)[:200],
            "url": d.final_url or d.url,
            "type": evidence_rules.classify_source(d.final_url or d.url),
            "retrieved_at": (d.fetched_at or d.retrieved_at).isoformat(),
            "rejected": {"reason": r.reason, "other": r.other},
        }
        for r, d in rejected_rows
    ]
    claim_src = {
        c.id: {
            "name": e.source_name,
            "url": e.url,
            "type": e.source_type,
            "retrieved_at": e.retrieved_at.isoformat(),
            "excerpt": c.excerpt,
            "favourite": bool(e.favourite),
            "extracted_by": c.extracted_by,
        }
        for c, e in rows
    }
    researched = max((r.completed_at for r in runs), default=v.created_at)
    return {
        "variant": v,
        "values": values,
        "claim_src": claim_src,
        "rejected_pages": rejected_pages,
        "researched_at": researched.isoformat(),
        "runs": {r.area: r for r in runs},
        "issues": [(i, e) for i, e in issues],
        "reviews": [(r, e) for r, e in reviews],
        "manufacturer_facts": facts_rows,
        "stats": stats,
    }


def _num(car: dict, key: str) -> float | None:
    sv = car["values"].get(key)
    return sv.value_num if sv is not None and sv.available else None


def _txt(car: dict, key: str) -> str | None:
    sv = car["values"].get(key)
    return sv.value_text if sv is not None and sv.available else None


def completeness(car: dict) -> float:
    vals = car["values"]
    relevant = [
        k
        for k in specs.ATTRS
        if not (k == "displacement" and car["variant"].powertrain == "BEV")
        and not (k == "battery_kwh" and car["variant"].powertrain in ("ICE", "MHEV", "HEV"))
    ]
    return sum(1 for k in relevant if vals.get(k) is not None and vals[k].available) / len(relevant)


@lru_cache
def severity_rules() -> reliability.SeverityRules:
    from automind.infrastructure.config import load_yaml

    return reliability.SeverityRules.from_config(load_yaml("severity.yaml"))


def merged_issues(car: dict) -> list[reliability.MergedIssue]:
    items = [
        reliability.IssueIn(
            component=i.component,
            description=i.description,
            domain=e.domain,
            severity_hint=i.severity_hint,
            age_from=i.age_from,
            age_to=i.age_to,
            mileage_from=i.mileage_from,
            mileage_to=i.mileage_to,
            evidence_id=e.id,
        )
        for i, e in car.get("issues", [])
    ]
    return reliability.merge_issues(items, severity_rules())


def reliability_summary(car: dict) -> ReliabilitySummary | None:
    run = car.get("runs", {}).get("reliability")
    if run is None:
        return None
    return reliability.summarize(merged_issues(car), minimum_met=bool(run.minimum_met))


def review_items(car: dict) -> list[reviews.ReviewIn]:
    return [
        reviews.ReviewIn(
            tag=r.tag, polarity=r.polarity, text=r.text, domain=e.domain, reviewer=r.reviewer, evidence_id=e.id
        )
        for r, e in car.get("reviews", [])
    ]


def review_summary(car: dict) -> ReviewSummary | None:
    if car.get("runs", {}).get("reviews") is None:
        return None
    return reviews.summarize_reviews(review_items(car))


ENGINEERING_ATTRS = [k for k, a in specs.ATTRS.items() if a.category == "engineering"]


def engineering_completeness(car: dict) -> float | None:
    if "engineering" not in car.get("runs", {}):
        return None
    vals = car["values"]
    return sum(1 for k in ENGINEERING_ATTRS if vals.get(k) is not None and vals[k].available) / len(ENGINEERING_ATTRS)


def facts(
    car: dict,
    sim: dragrace.CarResult | None = None,
    *,
    condition: str = "NEW",
    age_years: int | None = None,
    annual_cost_eur: float | None = None,
) -> scoring.CarFacts:
    v = car["variant"]
    return scoring.CarFacts(
        car_id=v.id,
        label=v.label,
        powertrain=v.powertrain,
        power_kw=_num(car, "max_power"),
        torque_nm=_num(car, "max_torque"),
        mass_kg=_num(car, "curb_mass"),
        displacement_cc=_num(car, "displacement"),
        drivetrain=_txt(car, "drivetrain"),
        top_speed_kmh=_num(car, "top_speed"),
        consumption=_num(car, "consumption"),
        boot_l=_num(car, "boot_volume"),
        seats=_num(car, "seats"),
        price_eur=_num(car, "official_price_es"),
        service_interval_km=_num(car, "service_interval_km"),
        service_interval_months=_num(car, "service_interval_months"),
        sim_0_100=sim.t_0_100 if sim else None,
        sim_400m=sim.t_400m if sim else None,
        rear_legroom_mm=_num(car, "rear_legroom"),
        ground_clearance_mm=_num(car, "ground_clearance"),
        low_range=_txt(car, "low_range"),
        euro_ncap=_num(car, "euro_ncap_stars"),
        vehicle_class=v.vehicle_class,
        brand_positioning=v.brand_positioning,
        condition=condition,
        age_years=age_years,
        annual_cost_eur=annual_cost_eur,
        reliability=reliability_summary(car),
        reviews=review_summary(car),
        engineering_completeness=engineering_completeness(car),
    )


def race_inputs(car: dict) -> dragrace.CarInput:
    v = car["variant"]
    return dragrace.CarInput(
        car_id=v.id,
        label=v.label,
        powertrain=v.powertrain,
        power_kw=_num(car, "max_power"),
        mass_kg=_num(car, "curb_mass"),
        drivetrain=_txt(car, "drivetrain"),
        transmission=_txt(car, "transmission"),
        top_speed_kmh=_num(car, "top_speed"),
        body_class=v.body_class,
        claimed_0_100=_num(car, "claimed_0_100"),
    )


def run_race(cars: list[dict], settings: dict | None = None) -> dragrace.RaceResult:
    st = {k: v for k, v in (settings or {}).items() if v is not None}
    return dragrace.simulate([race_inputs(c) for c in cars], dragrace.RaceSettings(**st))


# ---------------- blocks ----------------


def display(key: str, sv) -> str | None:
    if sv is None or not sv.available:
        return None
    if sv.value_text is not None:
        return sv.value_text
    x = sv.value_num
    unit = specs.ATTRS[key].unit
    if key == "max_power":
        return units.kw_to_hp_display(x)
    if key == "official_price_es":
        return f"{x:,.0f} €".replace(",", ".")
    if key == "consumption":
        return f"{x:g}"
    if key in ("seats", "service_interval_months"):
        return f"{x:.0f}" + (" months" if key == "service_interval_months" else "")
    if key in ("curb_mass", "displacement", "service_interval_km", "boot_volume"):
        return f"{x:,.0f} {unit}".replace(",", ".")
    return f"{x:g} {unit}" if unit else f"{x:g}"


def car_header(car: dict, from_cache: bool) -> dict:
    v = car["variant"]
    return {
        "id": v.id,
        "label": v.label,
        "powertrain": v.powertrain,
        "from_cache": from_cache,
        "researched_at": car["researched_at"],
    }


def spec_table(cars: list[dict], from_cache: dict[str, bool]) -> dict:
    rows = []
    for key in TABLE_ROWS:
        attr = specs.ATTRS[key]
        if all((c["values"].get(key) is None or not c["values"][key].available) for c in cars) and key in (
            "battery_kwh",
            "displacement",
            "service_interval_months",
        ):
            continue
        vals = []
        for c in cars:
            sv = c["values"].get(key)
            available = bool(sv is not None and sv.available)
            sources = [c["claim_src"][cid] for cid in (sv.claim_ids if available else []) if cid in c["claim_src"]][:4]
            vals.append(
                {
                    "car_id": c["variant"].id,
                    "available": available,
                    "display": display(key, sv),
                    "value": (sv.value_num if sv.value_num is not None else sv.value_text) if available else None,
                    "provenance": sv.provenance if available else None,
                    "confidence": sv.confidence if available else None,
                    "sources": sources,
                }
            )
        unit = "l or kWh /100 km" if key == "consumption" else attr.unit
        rows.append({"key": key, "label": attr.label, "unit": unit, "values": vals})
    return {
        "type": "spec_table",
        "title": "Specifications (validated, with sources)",
        "cars": [car_header(c, from_cache.get(c["variant"].id, False)) for c in cars],
        "rows": rows,
    }


def metric_bars(cars: list[dict]) -> dict:
    ms = {c["variant"].id: scoring.metrics(facts(c)) for c in cars}
    defs = [
        ("power_to_weight", "Power-to-weight", "kW/t", "higher"),
        ("weight_to_power", "Weight-to-power", "kg/kW", "lower"),
        ("torque_to_weight", "Torque-to-weight", "N·m/t", "higher"),
        ("specific_output", "Specific output", "kW/L", "higher"),
    ]
    return {
        "type": "metric_bars",
        "title": "Derived metrics (computed)",
        "metrics": [
            {
                "key": k,
                "label": lbl,
                "unit": u,
                "better": b,
                "values": [
                    {"car_id": c["variant"].id, "label": c["variant"].label, "value": ms[c["variant"].id][k]}
                    for c in cars
                ],
            }
            for k, lbl, u, b in defs
            if any(ms[c["variant"].id][k] is not None for c in cars)
        ],
    }


def race_block(race: dragrace.RaceResult, predicted_car_id: str | None = None) -> dict:
    """race_chart; with a user prediction it also says whether the prediction was right (US6)."""
    winner = next((r.car_id for r in race.results if r.rank == 1), None)
    return {
        "type": "race_chart",
        "prediction": predicted_car_id,
        "prediction_correct": (predicted_car_id == winner) if predicted_car_id and winner else None,
        "title": "Drag race 0–400 m",
        "model_version": race.model_version,
        "settings": asdict(race.settings),
        "series": [
            {"car_id": r.car_id, "label": r.label, "t": r.t, "v_kmh": r.v_kmh, "s_m": r.s_m} for r in race.results
        ],
        "results": [
            {
                "car_id": r.car_id,
                "label": r.label,
                "rank": r.rank,
                "t_0_100": r.t_0_100,
                "t_0_200": r.t_0_200,
                "t_400m": r.t_400m,
                "v_400m": r.v_400m,
                "claimed_0_100": r.claimed_0_100,
            }
            for r in race.results
        ],
        "excluded": race.excluded,
        "assumptions": [
            {
                "car_id": r.car_id,
                "items": [{"name": a["name"], "value": a["value"], "unit": a["unit"]} for a in r.assumptions],
            }
            for r in race.results
        ],
    }


def sources_block(cars: list[dict]) -> dict:
    """Accepted sources first (favourites marked, values read from tables flagged), then the pages rejected
    for another variant with their reasons (FR-012)."""
    seen: set[str] = set()
    items: list[dict] = []
    readers: dict[str, bool] = {}
    for c in cars:
        for src in c["claim_src"].values():
            readers[src["url"]] = readers.get(src["url"], False) or src.get("extracted_by") == "READER"
    for c in cars:
        for src in c["claim_src"].values():
            if src["url"] not in seen:
                seen.add(src["url"])
                item = {k: src[k] for k in ("name", "url", "type", "retrieved_at")}
                item["favourite"] = bool(src.get("favourite"))
                item["extracted_by"] = "READER" if readers.get(src["url"]) else "LLM"
                items.append(item)
    accepted = len(items)
    for c in cars:
        for src in c.get("rejected_pages", []):
            if src["url"] not in seen:
                seen.add(src["url"])
                items.append(src)
    return {"type": "sources", "title": f"Sources ({accepted})", "items": items}


def summary_for_llm(cars: list[dict], race: dragrace.RaceResult, criteria: CriteriaScore | None = None) -> dict:
    """Compact, validated facts for the analyst/hub prompt (numbers come only from here)."""
    out = {
        "cars": [],
        "race": {
            "model_version": race.model_version,
            "results": [
                {
                    "label": r.label,
                    "rank": r.rank,
                    "t_0_100": r.t_0_100,
                    "t_400m": r.t_400m,
                    "v_400m": r.v_400m,
                    "claimed_0_100": r.claimed_0_100,
                }
                for r in race.results
            ],
            "excluded": race.excluded,
        },
        "criteria_scores": _criteria_facts(criteria),
    }
    for c in cars:
        vals = {}
        for k in TABLE_ROWS:
            sv = c["values"].get(k)
            if sv is not None and sv.available:
                vals[k] = {"value": display(k, sv), "confidence": sv.confidence, "provenance": sv.provenance}
        out["cars"].append(
            {
                "label": c["variant"].label,
                "powertrain": c["variant"].powertrain,
                "specs": vals,
                "metrics": scoring.metrics(facts(c)),
                "missing": [k for k in TABLE_ROWS if k not in vals],
            }
        )

    return out


async def section_notices(cars: list[tuple[str, str]]) -> list[dict]:
    """'Insufficient data' per car and area whose minimum was not met (FR-019), also for cached reports.

    `cars` are (variant_id, label). Areas never researched are not reported here.
    """
    out = []
    async with db.sessionmaker()() as s:
        for vid, label in cars:
            runs = (
                await s.execute(
                    select(db.ResearchRun).where(
                        db.ResearchRun.variant_id == vid, db.ResearchRun.minimum_met.is_(False)
                    )
                )
            ).scalars()
            areas = sorted(r.area.replace("_", " ") for r in runs)
            if areas:
                out.append(
                    {
                        "type": "notice",
                        "level": "warning",
                        "text": f"{label}: insufficient data for {', '.join(areas)} (minimum evidence not reached).",
                    }
                )
    return out


# ---------------- spec 002 blocks ----------------


def criteria_block(sc: CriteriaScore, model: CriteriaModel, unmapped: list[str]) -> dict:
    """criteria_scores (contracts/chat-protocol.md): 0–100 indices, labelled as scores, with inputs."""
    return {
        "type": "criteria_scores",
        "title": "Criteria and scores (0–100 indices, not measurements)",
        "criteria_version": sc.criteria_version,
        "criteria": [
            {
                "key": k,
                "label": model.criteria[k].label,
                "weight": round(w, 1),
                "definition": model.criteria[k].definition,
            }
            for k, w in sorted(sc.weights.items(), key=lambda x: -x[1])
        ],
        "cars": [
            {
                "car_id": c.car_id,
                "label": c.label,
                "ranked": c.ranked,
                "total": c.total,
                "coverage": c.coverage,
                "parts": {
                    k: {"score": p.score, "insufficient": p.insufficient, "inputs": p.inputs}
                    for k, p in c.parts.items()
                },
            }
            for c in sc.cars
        ],
        "winner_car_id": sc.winner_car_id,
        "unmapped_wishes": list(unmapped),
    }


def case_summary_block(persona: str, facts_list: list[str], cars: list[dict]) -> dict:
    return {"type": "case_summary", "persona": persona, "facts": facts_list, "cars": cars}


def engineering_block(cars: list[dict]) -> dict | None:
    out = []
    for c in cars:
        items = []
        for k in ENGINEERING_ATTRS:
            sv = c["values"].get(k)
            if sv is None or not sv.available:
                continue
            items.append(
                {
                    "key": k,
                    "label": specs.ATTRS[k].label,
                    "display": display(k, sv) or "",
                    "confidence": sv.confidence or "LOW",
                    "sources": [_src(c, cid) for cid in (sv.claim_ids or []) if cid in c["claim_src"]],
                }
            )
        out.append({"car_id": c["variant"].id, "label": c["variant"].label, "items": items})
    if not any(x["items"] for x in out):
        return None
    return {"type": "engineering", "title": "Engineering", "cars": out}


def manufacturer_block(cars: list[dict]) -> dict | None:
    makes: dict[str, list[dict]] = {}
    for c in cars:
        make = c["variant"].make
        if make in makes:
            continue
        makes[make] = [
            {
                "kind": f.fact_type,
                "text": f.text,
                "sources": [
                    {
                        "name": f.source_name or f.url,
                        "url": f.url,
                        "type": "PUBLICATION",
                        "retrieved_at": f.retrieved_at.isoformat(),
                        "excerpt": f.excerpt,
                    }
                ],
            }
            for f in c.get("manufacturer_facts", [])[:6]
        ]
    if not any(makes.values()):
        return None
    return {
        "type": "manufacturer",
        "title": "Manufacturer",
        "makes": [{"make": m, "facts": f} for m, f in makes.items()],
    }


def _src(car: dict, claim_id: str) -> dict:
    return dict(car["claim_src"][claim_id])


def _criteria_facts(sc: CriteriaScore | None) -> dict | None:
    if sc is None:
        return None
    return {
        "note": "0–100 indices (scores), not measurements",
        "weights": {k: round(w, 1) for k, w in sc.weights.items()},
        "winner": next((c.label for c in sc.cars if c.car_id == sc.winner_car_id), None),
        "cars": [
            {
                "label": c.label,
                "total": c.total,
                "ranked": c.ranked,
                "coverage": c.coverage,
                "parts": {k: {"score": p.score, "inputs": p.inputs} for k, p in c.parts.items()},
            }
            for c in sc.cars
        ],
    }


# ---------------- ownership cost (US4) ----------------


async def tco_car(car: dict, condition: str, age_years: int | None, mileage_km: int | None) -> tco.TcoCar:
    """Assemble TCO inputs from validated data: specs, sourced maintenance items, used-car issues."""
    v = car["variant"]
    engine = (_txt(car, "engine") or "").lower()
    fuel = (
        "diesel"
        if any(k in engine for k in ("diesel", "tdi", "d-4d", "crdi", "dci", "hdi", "320d", "tdv"))
        else ("diesel" if "diesel" in v.variant_name.lower() or "d-4d" in v.variant_name.lower() else "petrol")
    )
    async with db.sessionmaker()() as s:
        maint = list(
            (await s.execute(select(db.MaintenanceItem).where(db.MaintenanceItem.variant_id == v.id))).scalars()
        )
        used = list(
            (
                await s.execute(select(db.Issue).where(db.Issue.variant_id == v.id, db.Issue.area == "used_issues"))
            ).scalars()
        )
    sched = [
        tco.MaintenanceSched(m.item, m.interval_km, m.interval_months, m.cost_eur, list(m.evidence_ids or []))
        for m in maint
        if m.interval_km or m.interval_months
    ]
    if not sched and (_num(car, "service_interval_km") or _num(car, "service_interval_months")):
        sched = [
            tco.MaintenanceSched("service", _num(car, "service_interval_km"), _num(car, "service_interval_months"))
        ]
    tickets = [
        tco.BigTicket(i.component, i.age_from, i.age_to, i.mileage_from, i.mileage_to, None, [i.evidence_id])
        for i in used
        if i.age_from is not None or i.mileage_from is not None
    ]
    return tco.TcoCar(
        car_id=v.id,
        label=v.label,
        powertrain=v.powertrain,
        fuel=None if v.powertrain == "BEV" else fuel,
        consumption=_num(car, "consumption"),
        vehicle_class=v.vehicle_class,
        condition=condition,
        age_years=age_years,
        mileage_km=mileage_km,
        fiscal_hp=_num(car, "fiscal_hp"),
        maintenance=sched,
        big_tickets=tickets,
    )


def tco_block(estimates: list[tco.TcoEstimate], evidence: dict[str, dict] | None = None) -> dict:
    ev = evidence or {}
    return {
        "type": "tco",
        "title": "Ownership cost (per year and over 5 years)",
        "annual_km": estimates[0].annual_km if estimates else 15000,
        "cars": [
            {
                "car_id": e.car_id,
                "label": e.label,
                "condition": "USED" if e.condition == "USED" else "NEW",
                "age_years": e.age_years,
                "annual_total": e.annual_total,
                "five_year_total": e.five_year_total,
                "items": [
                    {
                        "kind": i.kind,
                        "label": i.label,
                        "annual_eur": i.annual_eur,
                        "five_year_eur": i.five_year_eur,
                        "basis": i.basis,
                        "inputs": i.inputs,
                        "sources": [ev[x] for x in i.evidence_ids if x in ev],
                    }
                    for i in e.items
                ],
            }
            for e in estimates
        ],
    }


async def evidence_refs(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    async with db.sessionmaker()() as s:
        rows = (await s.execute(select(db.Evidence).where(db.Evidence.id.in_(ids)))).scalars()
        return {
            e.id: {
                "name": e.source_name,
                "url": e.url,
                "type": e.source_type,
                "retrieved_at": e.retrieved_at.isoformat(),
            }
            for e in rows
        }


async def persist_computations(
    turn_id: str,
    estimates: list[tco.TcoEstimate],
    cars: list[dict],
    race: dragrace.RaceResult | None,
    rates: dict,
    prediction: dict | None,
    mileage: dict[str, int | None],
) -> None:
    """Store TCO estimates and the race simulation of a turn (inputs, assumptions, versions; constitution IX)."""
    async with db.sessionmaker()() as s:
        for e in estimates:
            s.add(
                db.TcoEstimateRow(
                    turn_id=turn_id,
                    variant_id=e.car_id,
                    condition=e.condition,
                    age_years=e.age_years,
                    mileage_km=mileage.get(e.car_id),
                    annual_km=e.annual_km,
                    rates=rates,
                    items=[asdict(i) for i in e.items],
                    annual_total=e.annual_total,
                    five_year_total=e.five_year_total,
                    rules_version=e.rules_version,
                )
            )
        if race is not None and race.results:
            s.add(
                db.Simulation(
                    turn_id=turn_id,
                    model_version=race.model_version,
                    settings=asdict(race.settings),
                    prediction=prediction,
                    inputs=[asdict(race_inputs(c)) for c in cars],
                    assumptions=[{"car_id": r.car_id, "items": r.assumptions} for r in race.results],
                    results=[
                        {
                            "car_id": r.car_id,
                            "rank": r.rank,
                            "t_0_100": r.t_0_100,
                            "t_0_200": r.t_0_200,
                            "t_400m": r.t_400m,
                            "v_400m": r.v_400m,
                        }
                        for r in race.results
                    ],
                    input_hash=race.input_hash,
                )
            )
        await s.commit()


# ---------------- reliability and reviews (US5) ----------------


def _evidence_src(car: dict, evidence_ids: list[str]) -> list[dict]:
    by_id = {e.id: e for _, e in car.get("issues", [])} | {e.id: e for _, e in car.get("reviews", [])}
    return [
        {
            "name": by_id[x].source_name,
            "url": by_id[x].url,
            "type": by_id[x].source_type,
            "retrieved_at": by_id[x].retrieved_at.isoformat(),
        }
        for x in evidence_ids
        if x in by_id
    ]


def reliability_block(cars: list[dict], ages: dict[str, int | None]) -> dict | None:
    out = []
    for c in cars:
        v = c["variant"]
        run = c.get("runs", {}).get("reliability")
        if run is None:
            continue
        merged = reliability.order_for_age(merged_issues(c), ages.get(v.id))
        stats = []
        for st in c.get("stats", []):
            stats.append({"source": st.source, "metric": st.metric, "value": st.value, "year": st.year, "url": ""})
        out.append(
            {
                "car_id": v.id,
                "label": v.label,
                "minimum_met": bool(run.minimum_met),
                "issues": [
                    {
                        "component": m.component,
                        "description": m.description,
                        "recurrence": m.recurrence,
                        "severity": m.severity,
                        "age_window": m.age_window,
                        "sources": _evidence_src(c, m.evidence_ids),
                    }
                    for m in merged
                ],
                "stats": stats,
                "none_found": not merged,
            }
        )
    if not out:
        return None
    return {"type": "reliability", "title": "Reliability and known issues", "cars": out}


def reviews_block(cars: list[dict]) -> dict | None:
    out = []
    for c in cars:
        v = c["variant"]
        if c.get("runs", {}).get("reviews") is None:
            continue
        items = review_items(c)
        summary = reviews.summarize_reviews(items)
        points: dict[str, list[dict]] = {"PRO": [], "CON": []}
        seen: set[tuple[str, str]] = set()
        for r in items:
            rec_pc = summary.recurring.get(r.tag)
            recurring = bool(rec_pc and (rec_pc[0] if r.polarity == "PRO" else rec_pc[1]))
            key = (r.tag, r.polarity) if recurring else (r.tag + r.text, r.polarity)
            if key in seen:
                continue
            seen.add(key)
            points[r.polarity].append(
                {"tag": r.tag, "text": r.text, "recurring": recurring, "sources": _evidence_src(c, [r.evidence_id])}
            )
        for k in points:
            points[k].sort(key=lambda p: (not p["recurring"], p["tag"]))
        out.append(
            {
                "car_id": v.id,
                "label": v.label,
                "minimum_met": summary.minimum_met,
                "review_count": summary.review_count,
                "source_count": summary.source_count,
                "pros": points["PRO"][:6],
                "cons": points["CON"][:6],
            }
        )
    if not out:
        return None
    return {"type": "reviews", "title": "What reviewers and owners say", "cars": out}
