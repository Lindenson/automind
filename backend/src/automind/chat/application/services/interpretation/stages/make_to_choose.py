"""A make to choose from (009 FR-022, chat 20b5b7f9): "find me a Kia to replace my Prado 150". A make named without a
model next to a car the purchase replaces is the make the candidates come from, not a car to ask "which model?"
about; the car to replace is the person's own (used) car, compared with the candidates."""

from __future__ import annotations

import re

from automind.chat.domain import understanding
from automind.chat.domain.case import CaseCar, CaseFile
from automind.shared.contracts.config import MakeNames

_WORD = re.compile(r"[\w&-]+")  # "mercedes-benz", "b&w", "kia"


def make_to_choose_from(new: CaseFile, before: CaseFile, text: str, makes: MakeNames | None) -> list[str]:
    """Sets `new.wanted_make` and drops its bare car, marks the car replaced and the person's own car USED (in
    place). Returns the change log."""
    old = {c.key for c in before.cars}
    added = [c for c in new.cars if c.key not in old]
    # "my Toyota" is the person's own car, never the make to choose from
    bare = [c for c in added if c.make and not c.model and not c.replaced
            and not understanding.says_own(c.request_text)]  # fmt: skip
    replacing = understanding.replaces_a_car(text) or any(c.replaced for c in added)
    modelled = [c for c in added if c.model and c not in bare]
    log: list[str] = []
    if not new.wanted_make and replacing and modelled:
        make = bare[0].make if bare else _make_no_car_has(text, makes, modelled)
        if make:
            new.wanted_make = make
            log.append(f"make to choose from: {make}")
    if new.wanted_make:
        log += _drop_the_wanted_make(new, bare, added, replacing)
    for c in added:
        if c.replaced and c.condition == "UNKNOWN":  # the person's own car is a used one
            c.condition = "USED"
            log.append(f"{c.key}: used (the user's own car)")
    return log


def _make_no_car_has(text: str, makes: MakeNames | None, modelled: list[CaseCar]) -> str | None:
    """A make the words name that no car of this message has, when one car has a model (the interpreter dropped the
    Kia and kept the Prado only)."""
    taken = {(c.make or "").lower() for c in modelled}
    free = [m for m in _makes_named(text, makes) if m.lower() not in taken]
    return free[0] if len(modelled) == 1 and free else None


def _drop_the_wanted_make(new: CaseFile, bare: list[CaseCar], added: list[CaseCar], replacing: bool) -> list[str]:
    """The make to choose from is not a car of its own; with "to replace", the other new car is the one replaced."""
    wanted = (new.wanted_make or "").lower()
    drop = [c for c in bare if (c.make or "").lower() == wanted]
    new.cars = [c for c in new.cars if c not in drop]
    log = [f"{c.key} removed: {c.request_text} (a make to choose from)" for c in drop]
    if replacing and not any(c.replaced for c in new.cars):
        for c in added:
            if c in drop or not c.model or (c.make or "").lower() == wanted:
                continue
            c.replaced = True
            log.append(f"{c.key}: the car to replace")
    return log


def _makes_named(text: str, makes: MakeNames | None) -> list[str]:
    """The makes the words name exactly (an alias or a transliteration, one or two words), in order; a make right
    after "my" / "моего" / "mi" is the person's own car and is left out."""
    names = makes.names if makes is not None else {}
    words = _WORD.findall(text.lower())
    out: list[str] = []
    for i, w in enumerate(words):
        if any(understanding.is_own_word(x) for x in words[max(0, i - 2) : i]):
            continue
        make = names.get(" ".join(words[i : i + 2])) or names.get(w)
        if make and make not in out:
            out.append(make)
    return out
