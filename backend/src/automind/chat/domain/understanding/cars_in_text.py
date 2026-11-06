"""Splitting a message that names several cars into one segment per car."""

from __future__ import annotations

import re
from collections.abc import Callable

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
