"""The car as the report reads it: loaded from the engine's read model (`acquisition.api.car_data`) into one
dict, with accessors for its selected values, its new and used price, its warranty, the make's facts and the
sources of its claims."""

from __future__ import annotations

from collections.abc import Sequence

from automind.acquisition import api as acquisition
from automind.acquisition.api import CatalogueVariant
from automind.acquisition.api.car import ClaimRow, EvidenceRow, ManufacturerFactRow, SpecValueRow
from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.domain.identification import used
from automind.shared import evidence as evidence_rules
from automind.shared.contracts.json import JsonObject

ELECTRIC_ONLY = frozenset({"battery_kwh", "battery_gross_kwh", "battery_chemistry", "range_wltp", "range_real",
                           "range_cltc", "consumption_ev_cltc",
                           "consumption_ev", "consumption_ev_real", "consumption_ev_plug", "charge_ac_kw",
                           "charge_dc_peak_kw", "charge_dc_10_80_min", "heat_pump"})  # fmt: skip


PLUG_IN_ONLY = frozenset({"consumption_cs", "consumption_weighted"})


FACT_ORDER = ("WARRANTY", "BATTERY_WARRANTY", "NETWORK_ES", "MARKET_SHARE", "FINANCIAL", "RELIABILITY_REPUTATION",
               "MARKET_POSITION", "KEY_MODEL", "HISTORY")  # fmt: skip


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


async def load_car(variant_id: str) -> LoadedCar:
    """One car as the report reads it: its stored data (`acquisition.api.car_data`) with the sources of its claims,
    the pages rejected for it and the sources each area read. Raises KeyError for a version not in the catalogue."""
    data = await acquisition.car_data(variant_id)
    if data is None:
        raise KeyError(f"unknown variant {variant_id}")
    v = data.variant
    rejected_pages = [
        {
            "name": (p.title or p.url)[:200],
            "url": p.final_url or p.url,
            "type": evidence_rules.classify_source(p.final_url or p.url),
            "retrieved_at": (p.fetched_at or p.retrieved_at).isoformat(),
            "rejected": {"reason": p.reason, "other": p.other},
        }
        for p in data.rejected_pages
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
        for c, e in data.claims
    }
    researched = max((r.completed_at for r in data.runs), default=v.created_at)
    tried = await acquisition.tried_by_area(variant_id)
    return {
        "variant": v,
        "values": data.values,
        "cltc_pair": cltc_pair(data.claims, data.values.get("range_cltc")),
        "claim_src": claim_src,
        "rejected_pages": rejected_pages,
        "researched_at": researched.isoformat() if researched else None,
        "runs": {r.area: r for r in data.runs},
        "tried": {a: [t.model_dump() for t in ts] for a, ts in tried.items()},  # area -> sources read (T123)
        "issues": list(data.issues),
        "reviews": list(data.reviews),
        "manufacturer_facts": data.manufacturer_facts,
        "stats": data.stats,
        "retention": list(data.retention),
        # spec 008: sourced used-price ranges (the purchase price and value now of a used car)
        "used_prices": [
            used.UsedRange(float(r.min_eur), float(r.max_eur), r.model_year_from, r.model_year_to, r.url)
            for r in data.used_prices
        ],
        "maintenance": data.maintenance,  # sourced maintenance items (the ownership cost)
        "used_issues": data.used_issues,  # issues of used cars with an age or mileage (the ownership cost)
    }


def num(car: LoadedCar, key: str) -> float | None:
    """The car's number for an attribute, None when it has none (or it is marked not available)."""
    sv = car["values"].get(key)
    return sv.value_num if sv is not None and sv.available else None


def txt(car: LoadedCar, key: str) -> str | None:
    """The car's text for an attribute, None when it has none (or it is marked not available)."""
    sv = car["values"].get(key)
    return sv.value_text if sv is not None and sv.available else None


def new_price(car: LoadedCar) -> float | None:
    """The car's new price from its sources (research reads prices on European markets only, spec 009 FR-009)."""
    return num(car, "official_price_es")


def short_name(v: CatalogueVariant) -> str:
    """The name the text uses for a car: make and model (the full label is in the blocks)."""
    return f"{v.make} {v.model}".strip()


def used_price(car: LoadedCar, year: int | None) -> used.UsedPrice | None:
    """The sourced used price of this car for its year (spec 008 FR-023), or None."""
    return used.used_price_for(car.get("used_prices") or [], year)


def warranty_years(car: LoadedCar) -> float | None:
    """The maker's car warranty in years, from its sourced WARRANTY fact (spec 006 US6), or None."""
    for f in manufacturer_facts(car.get("manufacturer_facts", [])):
        if f.fact_type == "WARRANTY" and f.value_num:
            return float(f.value_num)
    return None


def manufacturer_facts(rows: list[ManufacturerFactRow]) -> list[ManufacturerFactRow]:
    """Two facts per kind at most, the situation first (share, finances, reliability, network), newest first."""
    by: dict[str, list[ManufacturerFactRow]] = {}
    for f in sorted(rows, key=lambda f: (-(getattr(f, "year", None) or 0), f.retrieved_at), reverse=False):
        by.setdefault(f.fact_type, []).append(f)
    out = []
    for kind in (*FACT_ORDER, *sorted(set(by) - set(FACT_ORDER))):
        out += by.get(kind, [])[:2]
    return out[:10]


def claim_source(car: LoadedCar, claim_id: str) -> JsonObject:
    """The source of a claim as the UI shows it (a copy)."""
    return dict(car["claim_src"][claim_id])


def evidence_sources(car: LoadedCar, evidence_ids: list[str]) -> list[JsonObject]:
    """The sources of issues and reviews by evidence id, as the UI shows them (unknown ids skipped)."""
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


def cltc_pair(
    rows: Sequence[tuple[ClaimRow, EvidenceRow]], selected: SpecValueRow | None
) -> tuple[float, float, str] | None:
    """(battery kWh, CLTC range km, url) of accepted claims read on one page, the selected range's page first: one
    version's pair. A battery and a range from different pages may be different versions (chat 2026-11-06: Li L9
    1st gen 42.8 kWh beside the 2026 car's 420 km)."""
    pages: dict[str, dict[str, float]] = {}
    for c, e in rows:
        if c.attribute in ("battery_kwh", "range_cltc") and c.value_num:
            pages.setdefault(e.url, {}).setdefault(c.attribute, float(c.value_num))
    pairs = [(p["battery_kwh"], p["range_cltc"], url) for url, p in pages.items() if len(p) == 2]
    want = selected.value_num if selected is not None and selected.available else None
    pairs.sort(key=lambda x: (x[1] != want, x[2]))
    return pairs[0] if pairs else None
