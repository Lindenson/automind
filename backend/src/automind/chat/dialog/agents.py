"""Persona reporters and the answerer: analyst agents with scoped MCP tools (constitution VIII; R10).

Least privilege: each role sees only the tools its report needs (contracts/rest-and-mcp.md). Analysts
read validated data; none of these tools touches the web. The usage callback on the model counts every
agent step (FR-042).
"""

from __future__ import annotations

from typing import Any

PROMPT = {"EXPERT": "reporter_expert", "PERFORMANCE": "reporter_performance", "BUYER": "reporter_buyer",
          "UNKNOWN": "reporter_balanced"}  # fmt: skip

_COMMON = {"get_case", "get_vehicle_specs", "compute_metrics", "score_criteria", "get_reliability"}
SCOPES: dict[str, set[str]] = {
    "reporter_buyer": _COMMON | {"compute_tco", "get_reviews"},
    "reporter_performance": _COMMON | {"simulate_drag_race"},
    "reporter_expert": _COMMON | {"simulate_drag_race", "get_engineering", "get_manufacturer"},
    "reporter_balanced": _COMMON | {"compute_tco", "get_reviews", "simulate_drag_race"},
    "answerer": _COMMON | {"compute_tco", "get_reviews", "simulate_drag_race", "get_engineering", "list_catalog"},
}


def prompt_name(role: str, persona: str) -> str:
    return PROMPT.get(persona, "reporter_balanced") if role == "reporter" else role


def scoped_tools(tools: list[Any], name: str) -> list[Any]:
    allowed = SCOPES[name]
    return [t for t in tools if getattr(t, "name", "") in allowed]
