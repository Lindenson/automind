"""Keeping the person own names of a model (never nearest: the same model): same_name, other_names, user_model,
keep_user_names."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from automind.chat.domain.case import CaseCar
from automind.shared.text.patterns import word_after_any

_NOT_ALNUM = re.compile(r"[\W_]")  # not a letter or digit: "Li-Auto L9" → "liautol9"


def _name_key(s: str | None) -> str:
    return _NOT_ALNUM.sub("", (s or "").lower())


def same_name(a: str | None, b: str | None) -> bool:
    """The same model name written another way ("S09", "s-09", "S 09", "Deepal S09" for make Deepal)."""
    return bool(a and b) and _name_key(a) == _name_key(b)


def other_names(asked: str | None, names: Iterable[str]) -> list[str]:
    """Alternatives to a model not found, never the very name asked (chat 2026-11-06: "I did not find «Deepal S09»
    on sale in Spain. Nearest: Deepal S09")."""
    return [n for n in names if not same_name(n, asked)]


_CODE = re.compile(r"^([^\W\d_]*)-?(\d+)([^\W\d_]*)$")  # a model code: S09, L9, X5, 320d


def _code(token: str) -> tuple[str, str, str] | None:
    m = _CODE.match(token.strip(".,;:!?»«\"'()"))
    return (m.group(1).lower(), m.group(2), m.group(3).lower()) if m else None


def user_model(car: CaseCar) -> str | None:
    """The model as the user named it ("L9" of "Lixiang L9"), unless the car was resolved to a confirmed model."""
    if car.resolution == "CONFIRMED" or not car.model:
        return car.model
    low = (car.request_text or "").lower()
    if car.model.lower() in low:
        i = low.index(car.model.lower())
        return car.request_text[i : i + len(car.model)]
    return car.model


def keep_user_names(sentence: str, cars: Sequence[CaseCar]) -> str:
    """The asker's sentence with each car under the model name the user gave (live chat 2026-11-06: "Deepal S09"
    came back as "Deepal S07", a sibling the model knew better). A model code after the car's make that differs
    from the user's code in its number only (S07 for S09, L7 for L9) is put back; other words are left alone."""
    out = sentence
    for car in cars:
        model = user_model(car)
        first = model.split()[0] if model else ""
        mine = _code(first) if first else None
        if mine is None or not car.make:
            continue
        makes = {car.make, *(w for w in (car.request_text or "").split() if w.lower() not in (model or "").lower())}
        alts = "|".join(re.escape(m) for m in sorted(makes, key=len, reverse=True) if _code(m) is None)
        if not alts:
            continue

        def put_back(m: re.Match[str], mine: tuple[str, str, str] = mine, first: str = first) -> str:
            said = _code(m.group(2))
            if said is None or said == mine or said[0] != mine[0] or len(said[1]) != len(mine[1]):
                return m.group(0)
            return f"{m.group(1)}{first}"

        out = word_after_any(alts).sub(put_back, out)
    return out
