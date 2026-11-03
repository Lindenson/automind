"""Clarifying questions (FR-005, FR-005a): code chooses ≤3 template questions; the asker phrases them.

The questions themselves are deterministic (policy + templates in config/questions.yaml). The model
only translates them into the user's language and adds one sentence acknowledging what it understood.
"""

from __future__ import annotations

import re
from collections.abc import Callable
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
        elif kind in ("CAR_IDENTITY", "USED_AGE", "TRIM", "UNKNOWN_MODEL", "GEARBOX"):
            for key in concerned:
                car = cars.get(key)
                if car is None or not _concerns(kind, car):
                    continue
                if kind == "UNKNOWN_MODEL":
                    opts = ", ".join(_closest(car)) or "make and model"
                else:
                    opts = ", ".join(generations.get(key, [])) or "year or generation"
                items.append(
                    {"kind": kind, "car": key, "text": tpl.format(car=car.request_text, options=opts, count=1)}
                )
        elif kind == "BUDGET_INTENT":
            b = case.budget
            amount = f"{b.max_eur:,} {b.currency}" + (" a month" if b.kind == "MONTHLY" else "")
            items.append({"kind": kind, "car": None, "text": tpl.format(car="", options=amount, count=0)})
        else:
            items.append({"kind": kind, "car": None, "text": tpl.format(car="", options="", count=0)})
    return items[:3]


def _closest(car: Any) -> list[str]:
    return [str(a.get("model")) for a in (car.alternatives or []) if isinstance(a, dict) and a.get("model")]


def quick_replies(
    items: list[dict[str, Any]], case: CaseFile, remove_label: Callable[[str], str], choose_label: str
) -> list[dict[str, str]]:
    """One-tap answers under a question (spec 004 FR-031): the closest known models for an unknown one,
    and "remove this car" for every car question. Labels come from the caller in the user's language."""
    out: list[dict[str, str]] = []
    cars = {c.key: c for c in case.cars}
    for q in items:
        car = cars.get(str(q.get("car") or ""))
        if car is None:
            continue  # questions about the user, not a car, get their replies below
        if q["kind"] == "UNKNOWN_MODEL":
            out += [{"label": m, "text": m} for m in _closest(car)]
        if q["kind"] in ("CAR_IDENTITY", "UNKNOWN_MODEL", "TRIM", "GEARBOX", "USED_AGE"):
            label = remove_label(car.request_text)
            out.append({"label": label, "text": label})
        if q["kind"] in ("TRIM", "GEARBOX"):
            out.append({"label": choose_label, "text": choose_label})

    return out[:6]


def _concerns(kind: str, car: Any) -> bool:
    if kind == "UNKNOWN_MODEL":
        return car.resolution == "UNKNOWN_MODEL"
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


# --- spec 005: localized templates (research R9) -------------------------------------------------------------


def template(questions: dict[str, Any], kind: str, lang: str | None, *, rephrase: bool = False,
             **values: object) -> str:  # fmt: skip
    """The question text of `kind` in `lang` (en if missing). With empty options the `bare` variant is used,
    so no literal fallback or empty "did you mean" ever reaches the user."""
    t = questions.get(kind) or {}
    if isinstance(t, str):  # v1 file
        t = {"en": t}
    lang = lang if lang in ("en", "ru", "es") else "en"
    opts = str(values.get("options") or "").strip()
    variant: dict[str, Any] = t
    if rephrase and isinstance(t.get("rephrase"), dict) and (opts or "{options}" not in str(t["rephrase"].get(lang))):
        variant = t["rephrase"]
    elif not opts and "{options}" in str(t.get(lang) or t.get("en") or "") and isinstance(t.get("bare"), dict):
        variant = t["bare"]
    text = str(variant.get(lang) or variant.get("en") or t.get("en") or "")
    vals = {"car": "", "make": "", "count": 0, **values, "options": opts}
    out = text.format(**vals)
    if not opts:  # a template without a bare variant: drop the empty options clause
        out = re.sub(r"\s*\(\s*\)", "", out).replace(": ?", "?").replace(": .", ".")
    return out
