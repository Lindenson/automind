"""Block value_retention (spec 004 FR-005): the share of the price kept after 3 and 5 years."""

from __future__ import annotations

from collections.abc import Callable

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.application.services.report.facts.retention import retention_points
from automind.shared.contracts.json import JsonObject


def value_retention_block(cars: list[LoadedCar], curve: dict[str, dict[float, float]],
                          recent: Callable[[str | None], bool] | None = None) -> JsonObject | None:  # fmt: skip
    """Value after 3 and 5 years per car (sourced, else the class curve; a recent make is marked insufficient); None
    when no car has a point."""

    def is_new(c: LoadedCar) -> bool:
        return bool(recent and recent(getattr(c["variant"], "make", None)))

    rows = [{"car_id": c["variant"].id, "label": c["variant"].label,
             "points": retention_points(c, curve, is_new(c)),
             **({"insufficient": True} if is_new(c) and not c.get("retention") else {})}
            for c in cars]  # fmt: skip
    if not any(r["points"] or r.get("insufficient") for r in rows):
        return None
    return {"type": "value_retention", "title": "Value after 3 and 5 years", "cars": rows}
