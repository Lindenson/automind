"""Deterministic analysis: load cached data, compute metrics/race/scores/costs, build UI blocks.

Used both by deterministic graph nodes and by the MCP server tools (same functions, same results).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select

from automind.acquisition import api as acquisition
from automind.domain import dragrace, energy, identity, reliability, reviews, specs, tco, units, used
from automind.domain import evidence as evidence_rules
from automind.domain import insights as ins
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
    "consumption_real",
    "consumption_nedc",
    # spec 006: electric facts (rows appear only when some car has a value)
    "battery_gross_kwh",
    "range_wltp",
    "range_real",
    "consumption_ev",
    "consumption_ev_real",
    "consumption_cs",
    "consumption_weighted",
    "charge_ac_kw",
    "charge_dc_peak_kw",
    "charge_dc_10_80_min",
    "boot_volume",
    "seats",
    "official_price_es",
    "service_interval_km",
    "service_interval_months",
]


ELECTRIC_ONLY = frozenset({"battery_kwh", "battery_gross_kwh", "battery_chemistry", "range_wltp", "range_real",
                           "consumption_ev", "consumption_ev_real", "consumption_ev_plug", "charge_ac_kw",
                           "charge_dc_peak_kw", "charge_dc_10_80_min", "heat_pump"})  # fmt: skip
PLUG_IN_ONLY = frozenset({"consumption_cs", "consumption_weighted"})


def relevant(key: str, powertrain: str | None) -> bool:
    """Whether an attribute applies to a powertrain (an ICE car has no battery; a BEV no displacement)."""
    pt = (powertrain or "ICE").upper()
    if key in PLUG_IN_ONLY:
        return pt in ("PHEV", "EREV")
    if key in ELECTRIC_ONLY - {"battery_kwh"}:
        return pt in ("BEV", "PHEV", "EREV")
    if key == "battery_kwh":
        return pt != "ICE"
    return not (key == "displacement" and pt == "BEV")


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
        retention = (
            await s.execute(
                select(db.ValueRetention, db.Evidence)
                .join(db.Evidence, db.ValueRetention.evidence_id == db.Evidence.id, isouter=True)
                .where(db.ValueRetention.variant_id == variant_id)
            )
        ).all()
        used_rows = (
            await s.execute(
                select(db.UsedPriceRange, db.Evidence.url)
                .join(db.Evidence, db.UsedPriceRange.evidence_id == db.Evidence.id)
                .where(db.UsedPriceRange.variant_id == variant_id, db.UsedPriceRange.status == "ACCEPTED")
            )
        ).all()
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
            # spec 011 FR-022 (010 T059): read from a registry candidate, labelled "unverified source"
            **({"unverified": True} if e.unverified else {}),
        }
        for c, e in rows
    }
    researched = max((r.completed_at for r in runs), default=v.created_at)
    tried = await acquisition.tried_by_area(variant_id)
    return {
        "variant": v,
        "values": values,
        "claim_src": claim_src,
        "rejected_pages": rejected_pages,
        "researched_at": researched.isoformat(),
        "runs": {r.area: r for r in runs},
        "tried": {a: [t.model_dump() for t in ts] for a, ts in tried.items()},  # area -> sources read (T123)
        "issues": [(i, e) for i, e in issues],
        "reviews": [(r, e) for r, e in reviews],
        "manufacturer_facts": facts_rows,
        "stats": stats,
        "retention": [(r, e) for r, e in retention],
        # spec 008: sourced used-price ranges (the purchase price and value now of a used car)
        "used_prices": [
            used.UsedRange(float(r.min_eur), float(r.max_eur), r.model_year_from, r.model_year_to, url)
            for r, url in used_rows
        ],
    }


def _num(car: dict, key: str) -> float | None:
    sv = car["values"].get(key)
    return sv.value_num if sv is not None and sv.available else None


def new_price(car: dict) -> float | None:
    """The car's new price from its sources (research reads prices on European markets only, spec 009 FR-009)."""
    return _num(car, "official_price_es")


def _txt(car: dict, key: str) -> str | None:
    sv = car["values"].get(key)
    return sv.value_text if sv is not None and sv.available else None


def completeness(car: dict) -> float:
    vals = car["values"]
    pt = car["variant"].powertrain
    keys = [k for k in specs.ATTRS if relevant(k, pt) and not (k == "battery_kwh" and pt in ("MHEV", "HEV"))]
    return sum(1 for k in keys if vals.get(k) is not None and vals[k].available) / len(keys)


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
    year: int | None = None,
    energy_eur_per_100km: float | None = None,
    mileage_km: int | None = None,
    used_price_eur: float | None = None,
    period_cost_eur: float | None = None,
    period_years: int | None = None,
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
        euro_ncap_year=_num(car, "euro_ncap_year"),
        vehicle_class=v.vehicle_class,
        brand_positioning=v.brand_positioning,
        condition=condition,
        age_years=age_years,
        mileage_km=mileage_km,
        used_price_eur=used_price_eur if condition == "USED" else None,
        annual_cost_eur=annual_cost_eur,
        period_cost_eur=period_cost_eur,
        period_years=period_years if period_cost_eur is not None else None,
        energy_eur_per_100km=energy_eur_per_100km,
        reliability=reliability_summary(car),
        reviews=review_summary(car),
        engineering_completeness=engineering_completeness(car),
        new_generation_since=scoring.new_generation_since(getattr(v, "generation_years_from", None), year),
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
    if key in ("consumption", "consumption_real", "consumption_nedc"):
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


_INSIGHT_OF_ROW = {"claimed_0_100": "accel_0_100"}


def spec_table(cars: list[dict], from_cache: dict[str, bool], insight_set: ins.InsightSet | None = None) -> dict:
    """The comparison table (spec 004 FR-016): only rows with data for at least one car; missing cells are
    marked; `better` marks the clearly best car of a meaningful difference (never a sub-threshold one)."""
    rows = []
    for key in TABLE_ROWS:
        attr = specs.ATTRS[key]
        if all((c["values"].get(key) is None or not c["values"][key].available) for c in cars):
            continue
        insight = insight_set.get(_INSIGHT_OF_ROW.get(key, key)) if insight_set is not None else None
        best = insight.better_car if insight is not None and insight.meaningful else None
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
                    "missing": not available,
                    "better": best == c["variant"].id,
                }
            )
        unit = "l or kWh /100 km" if key.startswith("consumption") else attr.unit
        meaningful = bool(insight is not None and insight.meaningful) if insight_set is not None else None
        rows.append({"key": key, "label": attr.label, "unit": unit, "values": vals, "meaningful": meaningful})
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
                if src.get("unverified"):
                    item["unverified"] = True
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
                "missing": [k for k in TABLE_ROWS if k not in vals and relevant(k, c["variant"].powertrain)],
            }
        )

    return out


DATA_AREAS = ("specs", "price", "maintenance", "reliability", "reviews", "measured", "engineering", "manufacturer",
              "depreciation", "used_issues", "used_price")  # fmt: skip
NO_SOURCES_RETRY_H = 12


def _tried_of(car: dict, area: str, run: Any) -> dict:
    """`{"tried": [...]}` for an area researched without an accepted value ("no data", spec 011 FR-022), else {}."""
    tried = (car.get("tried") or {}).get(area)
    if not tried or run is None or run.minimum_met or run.claims_accepted:
        return {}
    return {"tried": tried}


def data_panel_block(
    cars: list[tuple[str, str, dict]],
    areas: dict[str, set[str]],
    now: datetime | None,
    previous: dict[str, int] | None = None,
    tried: dict[str, list[str]] | None = None,
) -> dict | None:
    """One "what we know" panel instead of a warning per section (spec 004 FR-014, FR-015, SC-008).

    `cars` are (case car key, short name, loaded car); `areas` the areas each car needs (by case key).
    Status per area: COMPLETE (minimum met), PARTIAL (some evidence), MISSING (nothing yet), UNAVAILABLE
    (searched recently and no source found: no "find it" until the retry window). `previous` holds the
    accepted values per car from the last report, so the panel can say what changed after "find it". An area with
    no accepted value names the sources its research read, with their outcomes (`tried`, spec 011 FR-022)."""
    out, total_now = [], 0
    for key, name, car in cars:
        runs = car["runs"]
        rows = []
        for area in (a for a in DATA_AREAS if a in areas.get(key, set())):
            r = runs.get(area)
            if r is None:
                status, reason, findable = "MISSING", None, True
            elif r.minimum_met:
                status, reason, findable = "COMPLETE", None, False
            elif (r.claims_accepted or 0) > 0 or (r.docs_used or 0) > 0:
                status, reason, findable = "PARTIAL", "fewer independent sources than the minimum", True
            else:
                recent = now is not None and (now - r.completed_at).total_seconds() < NO_SOURCES_RETRY_H * 3600
                status = "UNAVAILABLE" if recent else "MISSING"
                reason, findable = "no usable sources found", not recent
            if findable and area in (tried or {}).get(car["variant"].id, []):
                reason, findable = "searched deeper: no more independent sources", False
            rows.append({"area": area, "status": status, "reason": reason, "findable": findable,
                         **_tried_of(car, area, r)})  # fmt: skip
        values = sum(1 for sv in car["values"].values() if sv.available)
        total_now += values
        out.append({"car_id": car["variant"].id, "car_key": key, "label": name, "values": values, "areas": rows})
    if not out:
        return None
    changed = None
    if previous:
        delta = total_now - sum(previous.values())
        if delta:
            changed = f"{delta:+d} values since the last report"
    return {"type": "data_panel", "cars": out, "changed": changed}


# ---------------- spec 002 blocks ----------------


def criteria_block(sc: CriteriaScore, model: CriteriaModel, unmapped: list[str], breakdown: Any = None) -> dict:
    """criteria_scores (contracts/chat-protocol.md): 0–100 scores computed from the sourced data, with the data each
    one is built from (per criterion and per car); each weight with its reasons (spec 007 FR-011)."""
    lines = breakdown.lines if breakdown is not None else {}
    return {
        "type": "criteria_scores",
        "title": "Criteria and scores (0–100, computed from the sourced data)",
        "criteria_version": sc.criteria_version,
        "criteria": [
            {
                "key": k,
                "label": model.criteria[k].label,
                "weight": round(w, 1),
                "definition": model.criteria[k].definition,
                "inputs": list(model.criteria[k].inputs),
                "reasons": [{"code": c, "points": p} for c, p in lines[k].contributions] if k in lines else [],
                "manual": lines[k].manual if k in lines else 0.0,
            }
            for k, w in sorted(sc.weights.items(), key=lambda x: -x[1])
        ],
        "manual_weights": bool(breakdown.manual) if breakdown is not None else False,
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
        "compared_on": list(sc.common),
        "tie": sc.tie,
        # spec 004 FR-010: the basis of each score: relative to the best compared car (= 100) and what could
        # not be compared because a car has no data for it
        "relative": _relative(sc),
        "not_compared": sorted(k for k in sc.weights if sc.weights[k] > 0 and k not in sc.common),
        "single": len(sc.cars) == 1,
    }


def _relative(sc: CriteriaScore) -> dict[str, dict[str, float]]:
    """Per criterion: each car's score relative to the best compared car (best = 100)."""
    out: dict[str, dict[str, float]] = {}
    if len(sc.cars) < 2:
        return out
    for k in sc.weights:
        scores = {c.car_id: c.parts[k].score for c in sc.cars if k in c.parts and c.parts[k].score is not None}
        best = max(scores.values(), default=None)
        if best and len(scores) >= 2:
            out[k] = {cid: round(100 * (v or 0) / best, 0) for cid, v in scores.items()}
    return out


def case_summary_block(persona: str, facts_list: list[str], cars: list[dict]) -> dict:
    return {"type": "case_summary", "persona": persona, "facts": facts_list, "cars": cars}


def engineering_block(cars: list[dict], explainers: dict | None = None) -> dict | None:
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
        out.append({"car_id": c["variant"].id, "label": c["variant"].label, "items": items,
                    "explainers": tech_explainers(c, explainers or {})})  # fmt: skip
    if not any(x["items"] or x["explainers"] for x in out):
        return None
    return {"type": "engineering", "title": "Engineering", "cars": out}


def tech_explainers(car: dict, cfg: dict) -> list[dict]:
    """What the car's drivetrain technology means (spec 004 FR-004): config text matched on the car's own
    validated gearbox / engine / powertrain, never web text. Most specific match first, at most two."""
    v = car["variant"]
    words = " ".join(
        str(x) for x in (_txt(car, "transmission"), _txt(car, "engine"), v.variant_name, v.powertrain,
                         v.transmission) if x
    ).lower()  # fmt: skip
    hits = []
    for key, e in (cfg.get("explainers") or {}).items():
        if any(m in words for m in e.get("match", [])):
            hits.append({"key": key, "title": e.get("title", key), "text": e.get("text", ""),
                         "consumption": e.get("consumption"), "reliability": e.get("reliability"),
                         "feel": e.get("feel"), "source": e.get("source", "editorial")})  # fmt: skip
    hybrid = {"power_split_hybrid", "series_hybrid"}
    if any(h["key"] in hybrid for h in hits):  # a hybrid's "automatic" label is not a torque converter
        hits = [h for h in hits if h["key"] not in ("torque_converter", "cvt")]
    return hits[:2]


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
                "year": getattr(f, "year", None),
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
            for f in _manufacturer_facts(c.get("manufacturer_facts", []))
        ]
    if not makes:
        return None
    # spec 004 FR-006: fewer than two facts for a make is shown as insufficient, with "find it"
    return {
        "type": "manufacturer",
        "title": "Manufacturer",
        "makes": [{"make": m, "facts": f, "insufficient": len(f) < 2} for m, f in makes.items()],
    }


_FACT_ORDER = ("WARRANTY", "BATTERY_WARRANTY", "NETWORK_ES", "MARKET_SHARE", "FINANCIAL", "RELIABILITY_REPUTATION",
               "MARKET_POSITION", "KEY_MODEL", "HISTORY")  # fmt: skip


def _manufacturer_facts(rows: list) -> list:
    """Two facts per kind at most, the situation first (share, finances, reliability, network), newest first."""
    by: dict[str, list] = {}
    for f in sorted(rows, key=lambda f: (-(getattr(f, "year", None) or 0), f.retrieved_at), reverse=False):
        by.setdefault(f.fact_type, []).append(f)
    out = []
    for kind in (*_FACT_ORDER, *sorted(set(by) - set(_FACT_ORDER))):
        out += by.get(kind, [])[:2]
    return out[:10]


def _src(car: dict, claim_id: str) -> dict:
    return dict(car["claim_src"][claim_id])


def _criteria_facts(sc: CriteriaScore | None) -> dict | None:
    if sc is None:
        return None
    return {
        "note": "0–100 indices (scores), not measurements. Totals use only `compared_on` (criteria every car has "
        "data for). `tie`: no winner — say the cars are close. Differences under 5 points in one criterion are not "
        "a win; never present a few litres or a few tenths as an advantage.",
        "weights": {k: round(w, 1) for k, w in sc.weights.items()},
        "winner": next((c.label for c in sc.cars if c.car_id == sc.winner_car_id), None),
        "compared_on": list(sc.common),
        "tie": sc.tie,
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


async def tco_car(
    car: dict, condition: str, age_years: int | None, mileage_km: int | None,
    retention_curve: dict | None = None, use: energy.UsageContext | None = None, new_in_market: bool = False,
    stated: dict[str, tuple[float, str]] | None = None, used_price_eur: float | None = None,
) -> tco.TcoCar:  # fmt: skip
    """Assemble TCO inputs from validated data: specs, sourced maintenance items, used-car issues."""
    v = car["variant"]
    fuel = getattr(v, "fuel", None)
    if fuel not in ("petrol", "diesel"):  # a hybrid kind or unknown: the liquid fuel from the engine and the name
        fuel = identity.liquid_fuel(f"{_txt(car, 'engine') or ''} {v.model} {v.variant_name}") or "petrol"
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
        consumption_real=_num(car, "consumption_real"),
        consumption_nedc=_num(car, "consumption_nedc"),
        consumption_ev=_num(car, "consumption_ev"),
        consumption_ev_real=_num(car, "consumption_ev_plug")
        or _num(car, "consumption_ev_real")
        or (_num(car, "consumption_real") if v.powertrain == "BEV" else None),
        ev_real_meter="plug" if _num(car, "consumption_ev_plug") else None,
        consumption_cs=_num(car, "consumption_cs"),
        consumption_weighted=_num(car, "consumption_weighted"),
        battery_kwh=_num(car, "battery_kwh"),
        range_wltp=_num(car, "range_wltp"),
        range_real=_num(car, "range_real"),
        use=use,
        vehicle_class=v.vehicle_class,
        condition=condition,
        age_years=age_years,
        mileage_km=mileage_km,
        fiscal_hp=_num(car, "fiscal_hp"),
        maintenance=sched,
        big_tickets=tickets,
        price_eur=_num(car, "official_price_es"),
        used_price_eur=used_price_eur if condition == "USED" else None,
        retention=sourced_retention(car),
        retention_curve=class_curve(v.vehicle_class, retention_curve or {}),
        new_in_market=new_in_market,
        stated=stated or {},
    )


def sourced_retention(car: dict) -> dict[int, float]:
    """Sourced value share per year (median when several sources), for the depreciation item (spec 007 FR-016)."""
    out: dict[int, float] = {}
    for years in RETENTION_YEARS:
        shares = sorted(float(r.share) for r, _ in car.get("retention", []) if r.years == years and r.share)
        if shares:
            out[years] = shares[len(shares) // 2]
    return out


def class_curve(vehicle_class: str | None, curves: dict) -> dict[float, float]:
    table = curves.get(vehicle_class or "compact") or curves.get("compact") or {}
    return {float(k): float(v) for k, v in table.items()}


def tco_block(estimates: list[tco.TcoEstimate], evidence: dict[str, dict] | None = None) -> dict:
    ev = evidence or {}
    years = estimates[0].years if estimates else 5
    return {
        "type": "tco",
        "title": f"Ownership cost (over {years} years including depreciation; running costs per year)",
        "annual_km": estimates[0].annual_km if estimates else 15000,
        "years": years,
        "cars": [
            {
                "car_id": e.car_id,
                "label": e.label,
                "condition": "USED" if e.condition == "USED" else "NEW",
                "age_years": e.age_years,
                "annual_total": e.annual_total,
                "five_year_total": e.five_year_total,
                **({"depreciation_left_out": True} if e.depreciation_left_out else {}),
                "items": [
                    {
                        "kind": i.kind,
                        "label": i.label,
                        "annual_eur": i.annual_eur,
                        "five_year_eur": i.five_year_eur,
                        "basis": i.basis,
                        "inputs": i.inputs,
                        "sources": [ev[x] for x in i.evidence_ids if x in ev],
                        **({"parts": [asdict(x) for x in i.parts]} if i.parts else {}),
                        **({"missing": i.missing} if i.missing else {}),
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
                    items=[{k: v for k, v in asdict(i).items() if k != "estimate"} for i in e.items],
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


# --- insights input (spec 004 FR-009) -----------------------------------------------------------------------

INSIGHT_ATTRS = ("boot_volume", "consumption", "measured_0_100", "max_power", "max_torque", "curb_mass",
                 "official_price_es", "ground_clearance", "rear_legroom", "euro_ncap_stars", "top_speed")  # fmt: skip


def short_name(v: db.Variant) -> str:
    """The name the text uses for a car: make and model (the full label is in the blocks)."""
    return f"{v.make} {v.model}".strip()


def insight_values(
    car: dict,
    *,
    annual_cost: float | None,
    reliability_score: float | None,
    energy_eur_per_unit: float | None,
    accel_0_100: float | None = None,
    retention_curve: dict | None = None,
    used: bool = False,
    used_price_eur: float | None = None,
    period_total: float | None = None,
    cost_curve: tuple[float, ...] = (),
) -> ins.CarValues:
    """A used car's price is what it costs used (spec 008 FR-023): its sourced used price, else no price at all —
    the new price never stands for a used car in the verdict or the text."""

    v = car["variant"]
    values: dict[str, float] = {}
    conf: dict[str, str] = {}
    srcs: dict[str, list[str]] = {}
    for k in INSIGHT_ATTRS:
        sv = car["values"].get(k)
        if sv is not None and sv.available and sv.value_num is not None:
            values[k], conf[k], srcs[k] = float(sv.value_num), str(sv.confidence or "MEDIUM"), list(sv.claim_ids or [])
    if used:
        values.pop("official_price_es", None)
        srcs.pop("official_price_es", None)
        if used_price_eur is not None:
            values["official_price_es"], conf["official_price_es"] = float(used_price_eur), "MEDIUM"
    claimed = car["values"].get("claimed_0_100")
    if claimed is not None and claimed.available and claimed.value_num is not None:
        values["accel_0_100"], conf["accel_0_100"] = float(claimed.value_num), str(claimed.confidence or "MEDIUM")
    elif accel_0_100 is not None:
        values["accel_0_100"], conf["accel_0_100"] = accel_0_100, "LOW"  # simulated
    # running costs per year (secondary) and the total over the user's period with the value lost (what ownership
    # cost compares, chat 5821ac77)
    costs = {k: x for k, x in (("tco_per_year", annual_cost), ("tco_period", period_total)) if x is not None}
    values |= costs
    conf |= dict.fromkeys(costs, "MEDIUM")
    if reliability_score is not None:
        values["reliability_score"], conf["reliability_score"] = reliability_score, "MEDIUM"
    five = next((p for p in retention_points(car, retention_curve or {}) if p["years"] == 5), None)
    if five is not None and five["share"]:
        values["value_retention_5y"] = round(five["share"] * 100, 1)
        conf["value_retention_5y"] = "MEDIUM" if five["basis"] == "SOURCED" else "LOW"
    return ins.CarValues(v.id, short_name(v), values, conf, srcs, energy_eur_per_unit, tuple(cost_curve))


# --- value retention (spec 004 FR-005) ----------------------------------------------------------------------

RETENTION_YEARS = (3, 5)


def retention_points(car: dict, curve: dict[str, dict[float, float]], new_in_market: bool = False) -> list[dict]:
    """Value left after 3 and 5 years: sourced points (median per year when several), else the labelled
    depreciation curve of the car's class (feasibility.yaml). A recent make gets no curve (spec 006 FR-018)."""
    v = car["variant"]
    out = []
    for years in RETENTION_YEARS:
        rows = [(r, e) for r, e in car.get("retention", []) if r.years == years and r.share is not None]
        if rows:
            shares = sorted(float(r.share) for r, _ in rows)
            mid = shares[len(shares) // 2]
            srcs = [{"name": e.source_name, "url": e.url, "type": e.source_type, "excerpt": r.excerpt,
                     "retrieved_at": e.retrieved_at.isoformat()} for r, e in rows if e is not None][:3]  # fmt: skip
            out.append({"years": years, "share": round(mid, 3), "eur": None, "basis": "SOURCED",
                        "market": rows[0][0].market, "sources": srcs,
                        "low": shares[0], "high": shares[-1]})  # fmt: skip
            continue
        if new_in_market:
            continue
        table = curve.get(v.vehicle_class or "compact") or curve.get("compact") or {}
        share = _interp(table, years)
        if share is not None:
            out.append({"years": years, "share": round(share, 3), "eur": None, "basis": "ASSUMPTION",
                        "market": "ES", "sources": [], "low": None, "high": None})  # fmt: skip
    price = _num(car, "official_price_es")
    for p in out:
        if price and p["share"]:
            p["eur"] = round(price * p["share"], -2)
    return out


def _interp(table: dict, years: float) -> float | None:
    pts = sorted((float(k), float(x)) for k, x in table.items())
    for (a, va), (b, vb) in zip(pts, pts[1:], strict=False):
        if a <= years <= b:
            return va + (vb - va) * (years - a) / (b - a)
    return None


def value_retention_block(cars: list[dict], curve: dict[str, dict[float, float]],
                          recent: Callable[[str | None], bool] | None = None) -> dict | None:  # fmt: skip
    def is_new(c: dict) -> bool:
        return bool(recent and recent(getattr(c["variant"], "make", None)))

    rows = [{"car_id": c["variant"].id, "label": c["variant"].label,
             "points": retention_points(c, curve, is_new(c)),
             **({"insufficient": True} if is_new(c) and not c.get("retention") else {})}
            for c in cars]  # fmt: skip
    if not any(r["points"] or r.get("insufficient") for r in rows):
        return None
    return {"type": "value_retention", "title": "Value after 3 and 5 years", "cars": rows}


def used_price(car: dict, year: int | None) -> used.UsedPrice | None:
    """The sourced used price of this car for its year (spec 008 FR-023), or None."""
    return used.used_price_for(car.get("used_prices") or [], year)


def warranty_years(car: dict) -> float | None:
    """The maker's car warranty in years, from its sourced WARRANTY fact (spec 006 US6), or None."""
    for f in _manufacturer_facts(car.get("manufacturer_facts", [])):
        if f.fact_type == "WARRANTY" and getattr(f, "value_num", None):
            return float(f.value_num)
    return None
