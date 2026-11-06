"""Applying the option a person picked from the ones offered (spec 007 F): a choice, a level, choose for me, inherited
condition."""

from __future__ import annotations

import re

from automind.chat.domain.case import CaseCar, CaseFile, Choice


def _plain_text(s: str | None) -> str:
    return " ".join(re.sub(r"[^\w+.\-()]", " ", (s or "").lower()).split())


def _without(label: str, *words: str | None) -> str:
    out = label
    for w in sorted({x for x in words if x}, key=len, reverse=True):
        out = re.sub(rf"(?i)(?<![\w]){re.escape(w)}(?![\w])", " ", out)
    return " ".join(out.split())


def _apply_choice(car: CaseCar, ch: Choice) -> str:
    """The user picked this option: it replaces what an earlier option left behind (generation, engine, version)."""
    from automind.shared.vehicle.identity import parse_engine  # local import: identity imports casefile lazily

    k = car.constraints
    if ch.level is not None:
        return _apply_level(car, ch)
    k.generation_hint = k.engine_hint = k.trim_hint = None
    car.make = ch.make or car.make
    car.model = ch.model or car.model
    car.identify = None
    if ch.variant_id:
        car.variant_id, car.label, car.resolution = ch.variant_id, ch.label, "CONFIRMED"
        return f"{car.key}: {ch.label} (picked)"
    car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    rest = _without(ch.label, car.make, car.model)
    if ch.variant_id is None and rest and (e := parse_engine(rest)) is not None and not e.empty():
        k.engine_hint = e
    return f"{car.key}: {ch.label} (picked)"


def _apply_level(car: CaseCar, ch: Choice) -> str:
    """An option of one ladder level (spec 008): its facts become the user's statement of that level; the levels
    above are kept, nothing is parsed from the label."""
    from automind.shared.vehicle.engine import EngineHint  # noqa: PLC0415

    k = car.constraints
    e = k.engine_hint.model_copy() if k.engine_hint else EngineHint()
    disp = round(ch.engine_cc / 1000, 1) if ch.engine_cc else None
    if ch.level == "FUEL":
        e = EngineHint(fuel=ch.fuel)  # type: ignore[arg-type]
        k.version_hint = None
    elif ch.level == "FAMILY":
        e = EngineHint(fuel=ch.fuel or e.fuel, displacement_l=disp, family=(ch.family or "")[:16] or None)  # type: ignore[arg-type]
        k.version_hint = None
    elif ch.level in ("ENGINE", "POWER"):
        e = EngineHint(fuel=ch.fuel or e.fuel, displacement_l=disp or e.displacement_l,  # type: ignore[arg-type]
                       family=(ch.family or "")[:16] or e.family, power_kw=ch.power_kw,
                       power_hp=round(ch.power_kw / 0.7355) if ch.power_kw else None)  # fmt: skip
        k.version_hint = ch.engine
    elif ch.level == "GEARBOX":
        k.gearbox_hint = ch.gearbox  # type: ignore[assignment]
        k.version_hint = ch.engine or k.version_hint
    elif ch.level == "DRIVE":
        k.drive_hint = ch.drive  # type: ignore[assignment]
        k.gearbox_hint = ch.gearbox or k.gearbox_hint  # type: ignore[assignment]
        k.version_hint = ch.engine or k.version_hint
    k.engine_hint = None if e.empty() else e
    if car.ladder is not None:  # the user's own answer: no longer a level the hub filled
        engine_levels = ch.level in ("FUEL", "FAMILY", "ENGINE", "POWER")
        for lvl in ("FUEL", "ENGINE", "POWER") if engine_levels else (str(ch.level),):
            car.ladder.origin.pop(lvl, None)
    car.variant_id, car.label, car.resolution, car.identify = None, None, "UNRESOLVED", None
    return f"{car.key}: {ch.label} (picked)"


def _choose_for_user(case: CaseFile, car: CaseCar) -> str:
    """ "Choose for me" after the identity could not be settled (chat 9b5c0b0c: "Audi A4 2.5 l, 2023" — no A4 of
    2023 has a 2.5): the engine, version and generation named are dropped, the facts that remain (make, model,
    year, mileage) decide, and the version found is taken without another question."""
    k = car.constraints
    k.generation_hint = k.engine_hint = k.trim_hint = None
    car.request_text = " ".join(x for x in (car.make, car.model) if x) or car.request_text
    car.variant_id, car.label, car.resolution, car.identify = None, None, "UNRESOLVED", None
    car.chosen_for_me = True
    case.intake.attempts.pop(car.key, None)  # a fresh start for this car, not straight back to "remove or choose"
    return f"{car.key}: choose for me (the named engine and version are dropped)"


def pick(case: CaseFile, text: str, *, gearbox_words: dict[str, str], yes: bool = False,
         choose: bool = False) -> tuple[CaseFile, list[str]] | None:  # fmt: skip
    """A reply that is exactly one of the offered options (a tapped chip, or the option typed) answers the pending
    question by code, without the interpreter: the option's variant, model or engine is set and the hints left by
    an earlier option are dropped. "Yes" to a proposal takes the proposed option; "choose for me" on a gearbox
    question takes the automatic; "choose for me" (or yes) to "remove or choose?" lets the hub choose.
    Returns None when the reply is not an offered option."""
    p = case.pending
    if p is None or p.kind != "QUESTIONS":
        return None
    said = _plain_text(text)
    if not said:
        return None
    new = case.model_copy(deep=True)
    logs: list[str] = []
    for item in p.items:
        key = str(item.get("car") or "")
        if not key or not any(c.key == key for c in new.cars):
            continue
        car = new.car(key)
        kind = item.get("kind")
        raw = item.get("choices")
        if kind == "GEARBOX" and not raw:  # the gearbox question of the older rules (no ladder options)
            gb = gearbox_words.get(said) or ("automatic" if choose else None)
            if gb:
                car.constraints.gearbox_hint = gb  # type: ignore[assignment]
                return new, [f"{key}: gearbox {gb}"]
            continue
        choices = [Choice.model_validate(x) for x in raw] if isinstance(raw, list) else []
        if (log := _answer(new, car, str(kind), choices, said, yes=yes, choose=choose)) is not None:
            logs.append(log)
            if not car.chosen_for_me or not (choices and choices[0].level):
                return new, logs
            # "choose for me" with several ladder questions open settles every one of them (spec 008 US3)
    return (new, logs) if logs else None


def _answer(case: CaseFile, car: CaseCar, kind: str, choices: list[Choice], said: str, *, yes: bool,
            choose: bool) -> str | None:  # fmt: skip
    """The option the reply takes for one question, applied to the car; None when it takes none."""
    if choices and choices[0].level is not None and (yes or choose) and not _label_hit(choices, said):
        # spec 008: "choose for me" (yes, go ahead, any) on a ladder question settles this level and the ones below
        car.chosen_for_me = True
        car.identify = None
        return f"{car.key}: choose for me ({kind.lower()} and below)"
    if kind == "PROPOSE" and (yes or choose) and choices:
        return _apply_choice(car, choices[0])
    if kind in ("REMOVE_OR_CHOOSE", "PROPOSE") and (yes or choose):
        return _choose_for_user(case, car)
    if choose and choices:  # "choose for me" on a list of versions, engines or models: the first suggested one
        ch = next((x for x in choices if x.suggested), choices[0])
        car.chosen_for_me = True
        return _apply_choice(car, ch) + " (chosen for the user)"
    hit = _label_hit(choices, said)
    return _apply_choice(car, hit) if hit is not None else None


def _label_hit(choices: list[Choice], said: str) -> Choice | None:
    return next((ch for ch in choices if _plain_text(ch.label) == said), None)


def inherit_condition(before: CaseFile, after: CaseFile) -> list[str]:
    """A car added later in the chat ("and the Mazda?") is bought like the cars already compared: when they all
    share a condition (and, if new, a year), the added car takes it instead of asking "new or used?" again."""
    old = {c.key for c in before.cars}
    others = [c for c in after.cars if c.key in old and not c.replaced]  # the user's own car is not bought
    conds = {c.condition for c in others}
    if len(conds) != 1 or "UNKNOWN" in conds:
        return []
    cond = next(iter(conds))
    years = {c.year for c in others}
    log = []
    for car in after.cars:
        if car.key in old or car.condition != "UNKNOWN":
            continue
        car.condition = cond
        if cond == "NEW" and len(years) == 1 and car.year is None:
            car.year = next(iter(years))
        log.append(f"{car.key}: {cond.lower()} like the other cars")
    return log
