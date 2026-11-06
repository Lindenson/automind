"""Block case_summary: what the comparison is about (persona, the person's facts, the cars)."""

from __future__ import annotations


def case_summary_block(persona: str, facts_list: list[str], cars: list[dict]) -> dict:
    return {"type": "case_summary", "persona": persona, "facts": facts_list, "cars": cars}
