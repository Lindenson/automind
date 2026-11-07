"""Value retention: the sourced share of the price kept after 3 and 5 years, else the class curve of
config/feasibility.yaml (none for a make new in the market, spec 006 FR-018)."""

from __future__ import annotations

from collections.abc import Mapping

from automind.chat.application.services.report.contracts import Curves, LoadedCar
from automind.chat.application.services.report.facts.car import num
from automind.shared.contracts.json import JsonObject

RETENTION_YEARS = (3, 5)


def retention_points(car: LoadedCar, curve: Curves, new_in_market: bool = False) -> list[JsonObject]:
    """Value left after 3 and 5 years: sourced points (median per year when several), else the labelled
    depreciation curve of the car's class (feasibility.yaml). A recent make gets no curve (spec 006 FR-018)."""
    v = car["variant"]
    out: list[JsonObject] = []
    for years in RETENTION_YEARS:
        rows = [(r, e) for r, e in car.get("retention", []) if r.years == years and r.share is not None]
        if rows:
            shares = sorted(float(s) for r, _ in rows if (s := r.share) is not None)
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
    price = num(car, "official_price_es")
    for p in out:
        if price and p["share"]:
            p["eur"] = round(price * p["share"], -2)
    return out


def sourced_retention(car: LoadedCar) -> dict[int, float]:
    """Sourced value share per year (median when several sources), for the depreciation item (spec 007 FR-016)."""
    out: dict[int, float] = {}
    for years in RETENTION_YEARS:
        shares = sorted(float(r.share) for r, _ in car.get("retention", []) if r.years == years and r.share)
        if shares:
            out[years] = shares[len(shares) // 2]
    return out


def class_curve(vehicle_class: str | None, curves: Curves) -> dict[float, float]:
    """The depreciation curve of a vehicle class (years -> share kept), the compact one by default."""
    table = curves.get(vehicle_class or "compact") or curves.get("compact") or {}
    return {float(k): float(v) for k, v in table.items()}


def _interp(table: Mapping[float, float], years: float) -> float | None:
    pts = sorted((float(k), float(x)) for k, x in table.items())
    for (a, va), (b, vb) in zip(pts, pts[1:], strict=False):
        if a <= years <= b:
            return va + (vb - va) * (years - a) / (b - a)
    return None
