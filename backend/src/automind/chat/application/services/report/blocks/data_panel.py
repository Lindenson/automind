"""Block data_panel (spec 004 FR-014): per car and area what is known, missing or findable, with the sources
tried — one panel instead of a warning per section."""

from __future__ import annotations

from datetime import datetime

from automind.acquisition.api.car import ResearchRunRow
from automind.chat.application.services.report.contracts import LoadedCar
from automind.shared.contracts.json import JsonObject

DATA_AREAS = ("specs", "price", "maintenance", "reliability", "reviews", "measured", "engineering", "manufacturer",
              "depreciation", "used_issues", "used_price")  # fmt: skip


NO_SOURCES_RETRY_H = 12


def data_panel_block(
    cars: list[tuple[str, str, LoadedCar]],
    areas: dict[str, set[str]],
    now: datetime | None,
    previous: dict[str, int] | None = None,
    tried: dict[str, list[str]] | None = None,
) -> JsonObject | None:
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


def _tried_of(car: LoadedCar, area: str, run: ResearchRunRow | None) -> JsonObject:
    """`{"tried": [...]}` for an area researched without an accepted value ("no data", spec 011 FR-022), else {}."""
    tried = (car.get("tried") or {}).get(area)
    if not tried or run is None or run.minimum_met or run.claims_accepted:
        return {}
    return {"tried": tried}
