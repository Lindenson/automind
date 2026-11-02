"""Clarifying questions (FR-005, FR-005a): code chooses ≤3 template questions; the asker phrases them.

The questions themselves are deterministic (policy + templates in config/questions.yaml). The model
only translates them into the user's language and adds one sentence acknowledging what it understood.
"""

from __future__ import annotations

from typing import Any

from automind.application.ports import LLM
from automind.domain.casefile import CaseFile, Pending, QuestionKind


def fill_questions(
    kinds: list[QuestionKind],
    case: CaseFile,
    templates: dict[str, str],
    generations: dict[str, list[str]],
    concerned: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cars = {c.key: c for c in case.cars}
    for kind in kinds:
        tpl = templates[kind]
        if kind == "TOO_MANY_CARS":
            opts = ", ".join(f"{c.key}: {c.request_text}" for c in case.cars)
            items.append({"kind": kind, "car": None, "text": tpl.format(options=opts, car="", count=len(case.cars))})
        elif kind in ("CAR_IDENTITY", "USED_AGE", "TRIM"):
            for key in concerned:
                car = cars.get(key)
                if car is None or not _concerns(kind, car):
                    continue
                opts = ", ".join(generations.get(key, [])) or "year or generation"
                items.append(
                    {"kind": kind, "car": key, "text": tpl.format(car=car.request_text, options=opts, count=1)}
                )
        else:
            items.append({"kind": kind, "car": None, "text": tpl.format(car="", options="", count=0)})
    return items[:3]


def _concerns(kind: str, car: Any) -> bool:
    if kind == "USED_AGE":
        return car.condition == "USED" and car.year is None
    if kind == "CAR_IDENTITY":
        return not (car.make and car.model)
    return True


async def phrase(llm: LLM, system_prompt: str, items: list[dict[str, Any]], language: str, understood: str) -> str:
    numbered = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(items, 1))
    return await llm.text(
        "asker",
        system_prompt,
        f"Language: {language}\nWhat I understood so far: {understood}\n\nQuestions (keep all, add none):\n{numbered}",
    )


def record(case: CaseFile, items: list[dict[str, Any]]) -> CaseFile:
    """Remember the questions as pending and as asked (one round only, FR-005)."""
    c = case.model_copy(deep=True)
    c.pending = Pending(kind="QUESTIONS", items=items)
    for q in items:
        if q["kind"] not in c.asked:
            c.asked.append(q["kind"])
    return c


def understood_summary(case: CaseFile) -> str:
    parts = []
    if case.persona != "UNKNOWN":
        parts.append(f"persona {case.persona.lower()}")
    for c in case.cars:
        bits = [c.request_text, c.condition.lower() if c.condition != "UNKNOWN" else ""]
        parts.append(" ".join(b for b in bits if b))
    if case.budget.max_eur:
        parts.append(f"budget up to €{case.budget.max_eur:,}")
    if case.priorities:
        parts.append("priorities: " + ", ".join(p.criterion for p in case.priorities))
    return "; ".join(parts) or "nothing yet"
