"""Persona block order (FR-030; contracts/chat-protocol.md). Pure.

Warning notices come first, info notices last; unknown block types are kept after the known ones.
A single car is a profile: no race chart and no winner (FR-012).
"""

from __future__ import annotations

from typing import Any

ORDER: dict[str, list[str]] = {
    "BUYER": [
        "case_summary", "feasibility", "criteria_scores", "tco", "electric", "reliability", "reviews", "spec_table",
        "sources",
    ],
    "PERFORMANCE": [
        "case_summary", "feasibility", "race_chart", "metric_bars", "criteria_scores", "spec_table", "reliability",
        "tco", "electric", "sources",
    ],
    "EXPERT": [
        "case_summary", "feasibility", "engineering", "spec_table", "metric_bars", "criteria_scores", "reliability",
        "manufacturer", "tco", "electric", "race_chart", "sources",
    ],
    "UNKNOWN": [
        "case_summary", "feasibility", "criteria_scores", "spec_table", "tco", "electric", "reliability", "race_chart",
        "sources",
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


# --- declarative sections (spec 004 FR-002, FR-019; config/report_layouts.yaml) --------------------------------


def section_of(block_type: str, layouts: dict[str, Any]) -> str | None:
    for key, sec in (layouts.get("sections") or {}).items():
        if block_type in (sec.get("blocks") or []):
            return str(key)
    return None


def annotate_sections(persona: str, blocks: list[dict[str, Any]], layouts: dict[str, Any]) -> list[dict[str, Any]]:
    """Tag each block with its section, whether it is open by default and its depth for this profile.
    The UI groups consecutive blocks of a section into one collapsible part; the order stays the persona's."""
    plan = {str(x["section"]): x for x in (layouts.get("layouts") or {}).get(persona, layouts.get("layouts", {})
                                                                            .get("UNKNOWN", []))}  # fmt: skip
    out = []
    for b in blocks:
        sec = section_of(str(b.get("type")), layouts)
        if sec is None or b.get("type") in ("verdict", "suggestions", "notice", "quick_replies"):
            out.append(b)
            continue
        cfg = plan.get(sec, {})
        out.append({**b, "section": sec, "open": bool(cfg.get("open", False)), "depth": cfg.get("depth", "summary")})
    return out


def depths(persona: str, layouts: dict[str, Any]) -> dict[str, str]:
    """Section → depth (summary | full) for the writer: the profile changes what is explained, not only the order."""
    rows = (layouts.get("layouts") or {}).get(persona) or (layouts.get("layouts") or {}).get("UNKNOWN", [])
    return {str(x["section"]): str(x.get("depth", "summary")) for x in rows if x.get("section") != "verdict"}
