"""Splitting a message that names several cars into one segment per car."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

_CAR_SPLIT = re.compile(r"\s+(?:и|или|vs\.?|versus|против|or|o|contra|against|y|and)\s+|[,;?!()¿¡]|\.(?:\s|$)", re.I)


def cars_in_text(text: str | None, match_make: Callable[[str], str | None]) -> list[tuple[str, str]]:
    """(the car's words, make) for each part of the message that names a known make, in order, one per make.
    A safety net (live run 2026-11-04): the interpreter once answered "compare BYD Seal U DM-i and SEAT Ateca"
    as a general question with no cars; two named cars are a comparison whatever the model says."""
    out: list[tuple[str, str]] = []
    for part in _CAR_SPLIT.split(text or ""):
        words = (part or "").split()
        make = match_make(" ".join(words)) if words else None
        if make is None or any(m == make for _, m in out):
            continue
        start = 0  # drop the words before the make ("Сравни BYD Seal U" → "BYD Seal U")
        for i in range(len(words)):
            if match_make(" ".join(words[i:])) == make and match_make(" ".join(words[i + 1 :])) != make:
                start = i
                break
        out.append((" ".join(words[start:]), make))
    return out


def makes_missed(text: str | None, have: Iterable[str | None], match_make: Callable[[str], str | None]) -> list[str]:
    """The makes the words name that are neither among `have` (the case's cars and the cars a reading added or
    replaced) — what a reading missed (spec 013 S4, chat 8ff3ae80: one reading in five dropped both cars of "мерседес
    c 200дизель 2026 и БМВ 220д 2024"). In the order written."""
    known = {m.lower() for m in have if m}
    return [make for _, make in cars_in_text(text, match_make) if make.lower() not in known]
