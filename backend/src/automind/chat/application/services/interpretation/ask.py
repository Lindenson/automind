"""Clarifying questions (FR-005, FR-005a): code chooses ≤3 template questions; the asker phrases them.

The questions themselves are deterministic (policy + templates in config/questions.yaml). The model
only translates them into the user's language and adds one sentence acknowledging what it understood.
"""

from __future__ import annotations

import re
from typing import Any

from automind.chat.domain.case import CaseCar, CaseFile, Pending, QuestionKind
from automind.chat.domain.identification import ladder
from automind.chat.domain.intake import intake
from automind.shared.contracts.llm import LLM


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
                    {
                        "kind": kind,
                        "car": key,
                        "text": tpl.format(car=car.display_name, options=opts, count=1, make=car.make or ""),
                    }
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


def _concerns(kind: str, car: Any) -> bool:
    if kind == "UNKNOWN_MODEL":
        return car.resolution == "UNKNOWN_MODEL" or bool(car.identify and car.identify.outcome == "NOT_FOUND")
    if kind == "MAKE_LINEUP":
        return bool(car.make) and not car.model
    if kind == "USED_AGE":
        return car.condition == "USED" and car.year is None
    if kind == "CAR_IDENTITY":
        return not car.make if car.identify is not None else not (car.make and car.model)
    if kind == "ENGINE" and car.identify is not None:  # never "which engine?" for a car already identified
        return car.identify.need == "ENGINE"
    if kind in ("FUEL", "POWER", "DRIVE") or (kind == "GEARBOX" and _laddered(car)):
        return car.identify is not None and car.identify.need == kind
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
        name = c.request_text  # the user's words, unless the car was resolved to another, confirmed model
        if c.resolution == "CONFIRMED" and c.make and c.model and c.model.lower() not in name.lower():
            name = f"{c.make} {c.model}"
        bits = [name, c.condition.lower() if c.condition != "UNKNOWN" else ""]
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
    if values.get("missing") and opts and isinstance(t.get("missing"), dict):
        variant = t["missing"]  # what the user named does not exist: said, then what does (spec 008 FR-004)
    elif rephrase and isinstance(t.get("rephrase"), dict) and (opts or "{options}" not in str(t["rephrase"].get(lang))):
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
             "PROPOSE": "CHOICE", "REMOVE_OR_CHOOSE": "CHOICE", "FUEL": "FUEL", "POWER": "POWER",
             "DRIVE": "DRIVE"}  # fmt: skip
CAR_KINDS = ("CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "ENGINE", "USED_AGE", "TRIM", "GEARBOX", "PROPOSE",
             "REMOVE_OR_CHOOSE", "FUEL", "POWER", "DRIVE")  # fmt: skip
LADDER_KINDS = ("FUEL", "ENGINE", "POWER", "GEARBOX", "DRIVE")  # spec 008: one level of the identification ladder


def _laddered(car: Any) -> bool:
    return bool(car.identify is not None and car.identify.level)


def ladder_words(questions: dict[str, Any], lang: str) -> dict[str, str]:
    """The ladder's words (fuels, gearboxes, drives, level names) in the conversation language."""
    raw = questions.get("LADDER_WORDS") or {}
    return {k: str(v.get(lang) or v.get("en") or k) for k, v in raw.items() if isinstance(v, dict)}


def _localized(choices: list[Any], words: dict[str, str]) -> list[Any]:
    """Option labels of the fuel, gearbox and drive levels in the user's language (a tap matches the label)."""
    out = []
    for ch in choices:
        label = ch.label
        if ch.level == "FUEL" and ch.fuel:
            label = words.get(ch.fuel, label)
        elif ch.level == "GEARBOX" and ch.gearbox in ("manual", "automatic", "single"):
            label = words.get("automatic" if ch.gearbox == "single" else ch.gearbox, label)
        elif ch.level == "DRIVE" and ch.drive:
            label = words.get(ch.drive, label)
        elif ch.level == "POWER" and ch.engine_kw and ch.years_from:  # a registered version (chat 6e001ee0)
            label = ladder.registered_label(ch.fuel, ch.engine_cc, ch.engine_kw, ch.power_is_max, ch.years_from,
                                            ch.years_to, words)  # fmt: skip
        out.append(ch.model_copy(update={"label": label}))
    return out


def _ladder_options(car: Any, choices: list[Any], questions: dict[str, Any],
                    lang: str) -> tuple[list[Any], list[str], str]:  # fmt: skip
    choices = _localized(choices, ladder_words(questions, lang))
    name = f"{car.make} {car.model}" + (f" {car.year}" if car.condition == "USED" and car.year else "")
    return choices, [ch.label for ch in choices[:6]], name


def _car_text(questions: dict[str, Any], kind: str, lang: str, car: Any, name: str, labels: list[str], *,
              rephrase: bool, ladder_q: bool) -> str:  # fmt: skip
    """A car question's text; a ladder question starts with where the car stands and says what does not exist."""
    missing = ", ".join(car.identify.missing) if ladder_q and car.identify is not None else ""
    if kind == "USED_AGE" and car.mileage_km and "USED_YEAR" in questions:
        kind = "USED_YEAR"  # the mileage was given: only the year is asked
    text = template(questions, kind, lang, rephrase=rephrase, car=name, make=car.make or name,
                    options=", ".join(labels), missing=missing)  # fmt: skip
    return f"{status_line(car, ladder_words(questions, lang))}\n{text}" if ladder_q else text


def status_line(car: Any, words: dict[str, str]) -> str:
    """Where the identification of this car stands (spec 008 FR-013)."""
    k = car.constraints
    w = ladder.wanted_of(k.engine_hint, engine=k.version_hint, gearbox=k.gearbox_hint, drive=k.drive_hint)
    w = ladder.without(w, car.identify.missing if car.identify is not None else [])
    gen = (car.ladder.generation if car.ladder else None) or k.generation_hint
    level = car.identify.level if car.identify is not None else None
    return ladder.status_line(f"{car.make} {car.model}", gen, car.year, car.year_assumed, w,
                              level.lower() if level else None, words)  # fmt: skip


def intake_questions(
    kinds: list[str],
    case: CaseFile,
    questions_i18n: dict[str, Any],
    generations: dict[str, list[str]],
    concerned: list[str],
    lang: str,
    gearboxes: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Question items in the conversation language with concrete options (spec 005 R9, FR-003, FR-009).
    A question asked before for the same car and item uses its `rephrase` wording. `gearboxes` are the gearbox
    names in the conversation language (the options of a GEARBOX question)."""
    gearboxes = gearboxes or {}
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
            choices, labels = _options(kind, car, generations.get(key, []), gearboxes)
            name = car.display_name
            ladder_q = kind in LADDER_KINDS and _laddered(car)
            if ladder_q:  # spec 008: options in the user's language, the car named by make, model and year
                choices, labels, name = _ladder_options(car, choices, questions_i18n, lang)
            if kind == "PROPOSE":
                proposal = choices[0].label if choices else (car.label or "")
                if not proposal:
                    kind, item = "REMOVE_OR_CHOOSE", "CHOICE"
                else:
                    name = proposal
            rephrase = case.intake.attempt(key, item) >= 1
            text = _car_text(questions_i18n, kind, lang, car, name, labels, rephrase=rephrase, ladder_q=ladder_q)
            items.append({"kind": kind, "car": key, "item": item, "text": text,
                          "choices": [ch.model_dump(mode="json") for ch in choices[:6]]})  # fmt: skip
    return items[:3]


def _distinct_generations(names: list[str]) -> list[str]:
    """ "B9" and "B9 (8W)" are one generation: offered once (live chat 8c6a2a58)."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        key = re.sub(r"\s*\(.*?\)", "", n).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(n)
    return out


def _options(kind: str, car: Any, generations: list[str], gearboxes: dict[str, str]) -> tuple[list[Any], list[str]]:
    """The offered choices of a car question and the option names in its text. A gearbox question offers
    gearboxes, never the car's versions (incident 2026-11-03)."""
    if kind == "GEARBOX" and not _laddered(car):
        return [], [gearboxes.get("automatic", "automatic"), gearboxes.get("manual", "manual")]
    choices = list(car.identify.choices) if car.identify else []
    labels = [ch.label for ch in choices[:6]]
    if kind == "USED_AGE" or (kind == "TRIM" and not labels):
        labels = _distinct_generations(generations)
    return choices, labels


MAX_CHIPS = 12


def _chip(label: str, ch: dict[str, Any] | None = None) -> dict[str, Any]:
    chip: dict[str, Any] = {"label": label, "text": label}
    if ch and ch.get("suggested"):
        chip |= {"suggested": True, "reason": ch.get("reason")}
    return chip


def _question_chips(q: dict[str, Any], car: Any, labels: dict[str, str]) -> tuple[list[dict[str, Any]], bool]:
    """A question's own answers, and whether it takes "choose for me"."""
    kind = q["kind"]
    if kind == "PROPOSE":
        return [_chip(labels["yes"]), _chip(labels["no"])], False
    own = [_chip(labels[x]) for x in ("automatic", "manual") if labels.get(x)] if (
        kind == "GEARBOX" and not q.get("choices")) else []  # fmt: skip
    own += [_chip(ch["label"], ch) for ch in q.get("choices") or []]
    chooses = kind in ("MAKE_LINEUP", "TRIM", "GEARBOX", "REMOVE_OR_CHOOSE", "FUEL", "POWER", "DRIVE") or (
        kind == "ENGINE" and bool(q.get("choices"))
    )
    if kind in ("ENGINE", "POWER") and labels.get("other") and _uncertain(car):
        # no sourced list: the options may miss the user's version, so typing it is offered too (chat 6e001ee0)
        own.append({"label": labels["other"], "text": labels["other"], "typing": True})
    return own, chooses


def _uncertain(car: Any) -> bool:
    return car.ladder is not None and car.ladder.certainty == "LESS_CERTAIN" and _laddered(car)


def _fair(groups: list[list[dict[str, Any]]], room: int) -> list[dict[str, Any]]:
    """Round-robin over the questions, so one car's long list never hides another car's options."""
    taken: list[list[dict[str, Any]]] = [[] for _ in groups]
    i = 0
    while room > 0 and any(len(t) < len(g) for t, g in zip(taken, groups, strict=True)):
        g, t = groups[i % len(groups)], taken[i % len(groups)]
        if len(t) < len(g):
            t.append(g[len(t)])
            room -= 1
        i += 1
    return [x for t in taken for x in t]


def intake_quick_replies(items: list[dict[str, Any]], case: CaseFile, labels: dict[str, str]) -> list[dict[str, Any]]:
    """One-tap answers: the concrete options of each question (suggested ones marked), new/used, yes/no for a
    proposal, "choose for me" and "remove …". The options are shared fairly between the questions; "choose for
    me", new/used and "remove …" are never cut (live chats 16c5fbc7, 8c6a2a58; contracts/intake-protocol.md)."""
    cars = {c.key: c for c in case.cars}
    groups: list[list[dict[str, Any]]] = []
    fixed: list[dict[str, Any]] = []
    removes: list[dict[str, Any]] = []
    for q in items:
        if q["kind"] == "CONDITION":
            fixed += [_chip(labels["new"]), _chip(labels["used"])]
            continue
        car = cars.get(str(q.get("car") or ""))
        if car is None:
            continue
        own, chooses = _question_chips(q, car, labels)
        groups.append(own)
        if chooses:
            fixed.append(_chip(labels["choose"]))
        if q["kind"] in CAR_KINDS:
            removes.append(_chip(labels["remove"].format(car=car.display_name)))
    seen: set[str] = set()

    def fresh(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [x for x in xs if x["label"] and not (x["label"] in seen or seen.add(x["label"]))]  # type: ignore[func-returns-value]

    fixed, removes = fresh(fixed), fresh(removes)
    groups = [fresh(g) for g in groups]
    answers = _fair(groups, max(MAX_CHIPS - len(fixed) - len(removes), 0)) if groups else []
    return [*answers, *fixed, *removes]


async def acknowledge(llm: LLM, system_prompt: str, language: str, understood: str,
                      cars: list[CaseCar] | None = None) -> str:  # fmt: skip
    """One sentence restating what was understood (asker v2); the questions are added by code. Each car keeps the
    model name the user gave (`cars`; live chat 2026-11-06: "Deepal S09" came back as "Deepal S07")."""
    text = (
        await llm.text("asker", system_prompt, f"Language: {language}\nWhat I understood so far: {understood}")
    ).strip()
    return intake.keep_user_names(text, cars or [])
