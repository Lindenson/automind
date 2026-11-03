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
                    {"kind": kind, "car": key, "text": tpl.format(car=car.display_name, options=opts, count=1, make=car.make or "")}
                )
        elif kind == "BUDGET_INTENT":
            b = case.budget
            amount = f"{b.max_eur:,} {b.currency}" + (" a month" if b.kind == "MONTHLY" else "")
            items.append({"kind": kind, "car": None, "text": tpl.format(car="", options=amount, count=0)})
        else:
            items.append({"kind": kind, "car": None, "text": tpl.format(car="", options="", count=0, make="")})
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
        return car.resolution == "UNKNOWN_MODEL" or bool(car.identify and car.identify.outcome == "NOT_FOUND")
    if kind == "MAKE_LINEUP":
        return bool(car.make) and not car.model
    if kind == "USED_AGE":
        return car.condition == "USED" and car.year is None
    if kind == "CAR_IDENTITY":
        return not car.make if car.identify is not None else not (car.make and car.model)
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
    elif rephrase and not opts and isinstance(t.get("rephrase_bare"), dict):
        variant = t["rephrase_bare"]
    elif not opts and "{options}" in str(t.get(lang) or t.get("en") or "") and isinstance(t.get("bare"), dict):
        variant = t["bare"]
    text = str(variant.get(lang) or variant.get("en") or t.get("en") or "")
    vals = {"car": "", "make": "", "count": 0, **values, "options": opts}
    out = text.format(**vals)
    if not opts:  # a template without a bare variant: drop the empty options clause
        out = re.sub(r"\s*\(\s*\)", "", out).replace(": ?", "?").replace(": .", ".")
    return out


# spec 005: question kind -> the intake item it asks about (attempt counters, repeat detection)
KIND_ITEM = {"CAR_IDENTITY": "MAKE", "MAKE_LINEUP": "MODEL", "UNKNOWN_MODEL": "MODEL", "ENGINE": "ENGINE",
             "CONDITION": "CONDITION", "USED_AGE": "YEAR", "TRIM": "CHOICE", "GEARBOX": "GEARBOX",
             "PROPOSE": "CHOICE", "REMOVE_OR_CHOOSE": "CHOICE"}  # fmt: skip
CAR_KINDS = ("CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "ENGINE", "USED_AGE", "TRIM", "GEARBOX", "PROPOSE",
             "REMOVE_OR_CHOOSE")  # fmt: skip


def intake_questions(
    kinds: list[str],
    case: CaseFile,
    questions_i18n: dict[str, Any],
    generations: dict[str, list[str]],
    concerned: list[str],
    lang: str,
) -> list[dict[str, Any]]:
    """Question items in the conversation language with concrete options (spec 005 R9, FR-003, FR-009).
    A question asked before for the same car and item uses its `rephrase` wording."""
    items: list[dict[str, Any]] = []
    cars = {c.key: c for c in case.cars}
    for kind in kinds:
        if kind == "TOO_MANY_CARS":
            opts = ", ".join(f"{c.key}: {c.display_name}" for c in case.cars)
            items.append({"kind": kind, "car": None, "item": None,
                          "text": template(questions_i18n, kind, lang, options=opts)})  # fmt: skip
            continue
        if kind == "BUDGET_INTENT":
            b = case.budget
            amount = f"{b.max_eur:,} {b.currency}" + (" / mes" if b.kind == "MONTHLY" else "")
            items.append({"kind": kind, "car": None, "item": None,
                          "text": template(questions_i18n, kind, lang, options=amount)})  # fmt: skip
            continue
        if kind not in CAR_KINDS:  # about the user or every car (CONDITION, PERSONA, …)
            item = KIND_ITEM.get(kind)
            rephrase = bool(item) and case.intake.attempt("*", item or "") >= 1
            items.append({"kind": kind, "car": None, "item": item,
                          "text": template(questions_i18n, kind, lang, rephrase=rephrase)})  # fmt: skip
            continue
        for key in concerned:
            car = cars.get(key)
            if car is None or not _concerns(kind, car):
                continue
            item = KIND_ITEM.get(kind, "MODEL")
            choices = list(car.identify.choices) if car.identify else []
            labels = [ch.label for ch in choices[:6]]
            if kind in ("USED_AGE", "GEARBOX") or (kind == "TRIM" and not labels):
                labels = list(generations.get(key, []))
            name = car.display_name
            if kind == "PROPOSE":
                proposal = choices[0].label if choices else (car.label or "")
                if not proposal:
                    kind, item = "REMOVE_OR_CHOOSE", "CHOICE"
                else:
                    name = proposal
            rephrase = case.intake.attempt(key, item) >= 1
            text = template(questions_i18n, kind, lang, rephrase=rephrase, car=name, make=car.make or name,
                            options=", ".join(labels))  # fmt: skip
            items.append({"kind": kind, "car": key, "item": item, "text": text,
                          "choices": [ch.model_dump(mode="json") for ch in choices[:6]]})  # fmt: skip
    return items[:3]


def intake_quick_replies(items: list[dict[str, Any]], case: CaseFile, labels: dict[str, str]) -> list[dict[str, Any]]:
    """One-tap answers: the concrete options of each question (suggested ones marked), new/used, yes/no for a
    proposal, remove or choose. Never an empty list item (contracts/intake-protocol.md)."""
    out: list[dict[str, Any]] = []
    cars = {c.key: c for c in case.cars}
    for q in items:
        kind = q["kind"]
        if kind == "CONDITION":
            out += [{"label": labels["new"], "text": labels["new"]}, {"label": labels["used"], "text": labels["used"]}]
            continue
        car = cars.get(str(q.get("car") or ""))
        if car is None:
            continue
        if kind == "PROPOSE":
            out += [{"label": labels["yes"], "text": labels["yes"]}, {"label": labels["no"], "text": labels["no"]}]
            continue
        for ch in q.get("choices") or []:
            chip: dict[str, Any] = {"label": ch["label"], "text": ch["label"]}
            if ch.get("suggested"):
                chip |= {"suggested": True, "reason": ch.get("reason")}
            out.append(chip)
        if kind in ("MAKE_LINEUP", "TRIM", "GEARBOX", "REMOVE_OR_CHOOSE"):
            out.append({"label": labels["choose"], "text": labels["choose"]})
        if kind in CAR_KINDS:
            rm = labels["remove"].format(car=car.display_name)
            out.append({"label": rm, "text": rm})
    seen: set[str] = set()
    return [x for x in out if x["label"] and not (x["label"] in seen or seen.add(x["label"]))][:8]  # type: ignore[func-returns-value]


async def acknowledge(llm: LLM, system_prompt: str, language: str, understood: str) -> str:
    """One sentence restating what was understood (asker v2); the questions are added by code."""
    return (
        await llm.text("asker", system_prompt, f"Language: {language}\nWhat I understood so far: {understood}")
    ).strip()
