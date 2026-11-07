"""Amounts a person writes in a message, as numbers: "25.000", "25 000", "25k", "20 тыщ", "1,5 млн" (constitution I:
a budget, a cost limit or a need must be written by the person, so the interpreter's numbers are checked against
these)."""

from __future__ import annotations

import re

# "20к" / "20k" is 20,000 but "20 км" / "20 km" is a distance (reviewer 2026-11-03: the Cyrillic к was missed).
# A space joins digits only as a thousands group ("25 000"); "Golf 7 2015" is 7 and 2015 (spec 007 FR-004).
_AMOUNT = re.compile(
    r"(\d{1,3}(?:[\s .,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)\s*"
    r"([kк](?![a-zа-яё])|mil\b|тыс\w*|тыщ\w*|thousand|млн\w*|mill[oó]n\w*|million\w*)?",
    re.I,
)
_SPACE = re.compile(r"\s")  # "25 000" → "25000"
_GROUPED = re.compile(r"\d{1,3}([.,]\d{3})+")  # "25.000", "1,500,000": thousands groups
_ONE_GROUP = re.compile(r"\d[.,]\d{3}")  # "1,500": a decimal before "млн", a thousands group otherwise


def amounts_in(text: str) -> set[float]:
    """Every amount written in `text`, multipliers applied: '25.000', '25,000', '25 000', '25k', '25 mil', '25 тыс',
    'до 20 тыщ' → 25000, 20000; '1,5 млн' → 1,500,000. Unparseable digits are skipped."""
    out: set[float] = set()
    for m in _AMOUNT.finditer(text):
        raw = _SPACE.sub("", m.group(1))
        word = m.group(2)
        if _GROUPED.fullmatch(raw) and not (word and _ONE_GROUP.fullmatch(raw) and _multiplier(word) > 1000):
            raw = raw.replace(".", "").replace(",", "")
        else:
            raw = raw.replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            continue
        out.add(round(v * _multiplier(word), 6))
    return out


def _multiplier(word: str | None) -> float:
    if not word:
        return 1.0
    return 1_000_000.0 if word.lower().startswith(("млн", "mill")) else 1000.0
