"""Feasibility of the case's constraints (spec 003 US3; FR-018..FR-023).

Gathers validated facts per car (official price, ownership cost, seats, boot, power, weight, battery,
editorial used-price ranges), runs the pure `domain.feasibility` rules, persists the result
(`feasibility_checks`) and builds the `feasibility` block. Numbers come only from here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from automind.application import compose
from automind.domain import feasibility as fz
from automind.domain import tco
from automind.domain.casefile import CaseFile


class FeasibilityStore(Protocol):
    async def used_ranges(self, variant_id: str) -> list[tuple[Any, str]]: ...  # (UsedPriceRange row, url)

    async def save_checks(self, chat_id: str, turn_id: str, rows: list[dict[str, Any]]) -> None: ...


CHECK_LABEL = {
    "BUDGET": "Budget",
    "RUNNING_COST": "Running cost",
    "USAGE_SPACE": "Space",
    "USAGE_POWER": "Power for your use",
    "USAGE_RANGE": "Range",
}


def needs_of(case: CaseFile) -> fz.Needs:
    b = case.budget
    return fz.Needs(
        budget_amount=float(b.max_eur) if b.max_eur else None,
        budget_currency=b.currency,
        budget_kind=b.kind,
        intent=b.intent,
        running_month_eur=case.running_cost_limit.per_month if case.running_cost_limit else None,
        passengers=case.needs.passengers,
        luggage=case.needs.luggage,
        mountains="MOUNTAINS" in case.usage,
        towing_kg=case.needs.towing_kg,
        daily_km=case.needs.daily_km,
    )


def has_constraints(case: CaseFile) -> bool:
    return needs_of(case).any()


def _fact(car: dict[str, Any], key: str) -> fz.Fact | None:
    sv = car["values"].get(key)
    if sv is None or not sv.available or sv.value_num is None:
        return None
    sources = [car["claim_src"][cid]["url"] for cid in (sv.claim_ids or []) if cid in car["claim_src"]][:3]
    return fz.Fact(float(sv.value_num), "SOURCED", tuple(sources))


async def _used_ranges(store: FeasibilityStore, variant_id: str) -> list[fz.UsedRange]:
    return [
        fz.UsedRange(
            r.model_year_from,
            r.model_year_to,
            float(r.min_eur),
            float(r.max_eur),
            url,
            r.quoted_on.isoformat() if r.quoted_on else None,
        )  # fmt: skip
        for r, url in await store.used_ranges(variant_id)
    ]


async def car_facts(case: CaseFile, rates_cfg: dict[str, Any], store: FeasibilityStore) -> list[fz.CarFacts]:
    rates = tco.TcoRates.from_config(rates_cfg, case.rates_override.model_dump())
    out = []
    for x in case.cars:
        if not x.variant_id:
            continue
        car = await compose.load_car(x.variant_id)
        cond = x.condition if x.condition in ("NEW", "USED") else "NEW"
        est = tco.compute(await compose.tco_car(car, cond, x.age_years, x.mileage_km), rates, case.annual_km)
        inputs = [f"{case.annual_km:,} km/year"] + [
            f"{i.label}: {', '.join(i.inputs)}" for i in est.items if i.basis == "ASSUMPTION" and i.inputs
        ][:3]
        v = car["variant"]
        out.append(
            fz.CarFacts(
                key=x.key, label=x.label or x.request_text, condition=x.condition, age_years=x.age_years,
                vehicle_class=v.vehicle_class, price=_fact(car, "official_price_es"),
                tco_annual=fz.Fact(est.annual_total, "ASSUMPTION", (), tuple(inputs)),
                seats=_fact(car, "seats"), boot_l=_fact(car, "boot_volume"), power_kw=_fact(car, "max_power"),
                mass_kg=_fact(car, "curb_mass"), battery_kwh=_fact(car, "battery_kwh"),
                consumption=_fact(car, "consumption") if v.powertrain == "BEV" else None,
                powertrain=v.powertrain, range_wltp=_fact(car, "range_wltp") if v.powertrain == "BEV" else None,
                used_ranges=tuple(await _used_ranges(store, v.id)),
            )
        )  # fmt: skip
    return out


async def evaluate(
    case: CaseFile, rules: dict[str, Any], rates_cfg: dict[str, Any], year: int, store: FeasibilityStore
) -> dict[str, Any]:
    """{results, fingerprint} as JSON-ready data (kept in the turn state for the node and the block)."""
    needs = needs_of(case)
    if not needs.any():
        return {"results": [], "fingerprint": None}
    results = fz.evaluate(needs, await car_facts(case, rates_cfg, store), rules, year)
    return {"results": [asdict(r) for r in results], "fingerprint": fz.fingerprint(needs, results)}


async def persist(store: FeasibilityStore, chat_id: str, turn_id: str, case: CaseFile, data: dict[str, Any]) -> None:
    by_key = {c.key: c.variant_id for c in case.cars}
    rows = [
        {"variant_id": by_key[r["car_key"]], "check": c["check"], "verdict": c["verdict"], "details": c}
        for r in data.get("results", [])
        if by_key.get(r["car_key"])
        for c in r["checks"]
    ]
    await store.save_checks(chat_id, turn_id, rows)


def constraint_lines(case: CaseFile) -> list[str]:
    b, out = case.budget, []
    if b.max_eur:
        what = {"NEW": "new", "USED": "used", "ANY": "new or used"}.get(b.intent, "")
        per = " a month" if b.kind == "MONTHLY" else ""
        out.append(f"Budget {b.max_eur:,} {b.currency}{per}" + (f" ({what})" if what else ""))
    if case.running_cost_limit:
        r = case.running_cost_limit
        out.append(f"Running cost up to €{r.amount_eur:,.0f} per {r.period.lower()}")
    n = case.needs
    if n.passengers:
        out.append(f"{n.passengers} people, {n.luggage.lower()} luggage")
    if "MOUNTAINS" in case.usage:
        out.append("Mountain driving")
    if n.towing_kg:
        out.append(f"Towing {n.towing_kg:,} kg")
    if n.daily_km:
        out.append(f"{n.daily_km} km a day")
    return out


def block(case: CaseFile, data: dict[str, Any]) -> dict[str, Any] | None:
    if not data.get("results"):
        return None

    def num(n: dict[str, Any]) -> dict[str, Any]:
        return {"label": n["label"], "value": n["value"], "unit": n["unit"], "basis": n["basis"],
                "sources": [{"name": u, "url": u, "type": "PUBLICATION", "retrieved_at": ""} for u in n["sources"]],
                "inputs": list(n["inputs"])}  # fmt: skip

    cars = []
    for r in data["results"]:
        checks = []
        for c in r["checks"]:
            item = {"check": c["check"], "label": CHECK_LABEL[c["check"]], "verdict": c["verdict"],
                    "summary": c["summary"], "compared": [num(n) for n in c["compared"]]}  # fmt: skip
            if c.get("used_age"):
                ua = c["used_age"]
                item["used_age"] = {"from_years": ua["from_years"], "to_years": ua["to_years"], "basis": ua["basis"]}
            if c.get("missing"):
                item["missing"] = list(c["missing"])
            checks.append(item)
        cars.append({"car_id": r["car_key"], "label": r["label"], "checks": checks})
    return {"type": "feasibility", "title": "Does it fit your case?", "constraints": constraint_lines(case),
            "cars": cars}  # fmt: skip


def problems(data: dict[str, Any]) -> list[str]:
    """One line per check that is not FITS (for the reply text and the confirmation)."""
    return [
        f"{r['label']}: {c['summary']}" for r in data.get("results", []) for c in r["checks"] if c["verdict"] != "FITS"
    ]
