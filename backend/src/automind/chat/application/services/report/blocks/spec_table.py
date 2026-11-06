"""Block spec_table: the compared cars' specifications side by side, with insight marks."""

from __future__ import annotations

from automind.chat.application.services.report.facts.display import TABLE_ROWS, display
from automind.chat.domain.verdict import insights as ins
from automind.shared.vehicle import specs


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
