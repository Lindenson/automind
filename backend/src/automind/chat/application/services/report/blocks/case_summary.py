"""Block case_summary: what the comparison is about (persona, the person's facts, the cars)."""

from __future__ import annotations

from automind.shared.contracts.json import JsonObject


def case_summary_block(persona: str, facts_list: list[str], cars: list[JsonObject]) -> JsonObject:
    """The case at a glance: the persona, the facts the person gave and each car as the UI lists it."""
    return {"type": "case_summary", "persona": persona, "facts": facts_list, "cars": cars}
