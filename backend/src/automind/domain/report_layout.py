"""Persona block order (FR-030; contracts/chat-protocol.md). Pure.

Warning notices come first, info notices last; unknown block types are kept after the known ones.
A single car is a profile: no race chart and no winner (FR-012).
"""

from __future__ import annotations

from typing import Any

ORDER: dict[str, list[str]] = {
    "BUYER": [
        "case_summary", "feasibility", "criteria_scores", "tco", "reliability", "reviews", "spec_table", "sources",
    ],
    "PERFORMANCE": [
        "case_summary", "feasibility", "race_chart", "metric_bars", "criteria_scores", "spec_table", "reliability",
        "tco", "sources",
    ],
    "EXPERT": [
        "case_summary", "feasibility", "engineering", "spec_table", "metric_bars", "criteria_scores", "reliability",
        "manufacturer", "tco", "race_chart", "sources",
    ],
    "UNKNOWN": [
        "case_summary", "feasibility", "criteria_scores", "spec_table", "tco", "reliability", "race_chart", "sources",
    ],
}  # fmt: skip


def order_blocks(persona: str, blocks: list[dict[str, Any]], *, cars: int) -> list[dict[str, Any]]:
    order = ORDER.get(persona, ORDER["UNKNOWN"])
    warnings = [b for b in blocks if b.get("type") == "notice" and b.get("level") == "warning"]
    infos = [b for b in blocks if b.get("type") == "notice" and b.get("level") != "warning"]
    content = [b for b in blocks if b.get("type") != "notice"]
    if cars == 1:
        content = [b for b in content if b.get("type") != "race_chart"]
        content = [{**b, "winner_car_id": None} if b.get("type") == "criteria_scores" else b for b in content]
    known = sorted((b for b in content if b.get("type") in order), key=lambda b: order.index(b["type"]))
    other = [b for b in content if b.get("type") not in order and b.get("type") not in _DROPPED]
    return [*warnings, *known, *other, *infos]


# Blocks of the persona layout that a persona does not show (e.g. reviews for performance) are dropped,
# except types unknown to every layout, which are kept at the end.
_DROPPED = {t for layout in ORDER.values() for t in layout}
