"""Yearly distance from the person words: 1-2 тыс км в месяц is 12,000-24,000 km a year (FR-016)."""

from __future__ import annotations

import re

_NUM = r"\d{1,3}(?:[  .]\d{3})+|\d+(?:[.,]\d+)?"

_THOUSANDS = re.compile(r"\d{1,3}(?:[ .]\d{3})+")  # grouped thousands: "12 000", "1.500"
_GROUP_SEP = re.compile(r"[ .]")  # a thousands separator: the space or dot in "12 000"


_DIST = re.compile(
    rf"({_NUM})(?:\s*[-–—]\s*({_NUM}))?\s*(тыс\w*\.?|k\b|mil\b)?\s*(?:км|km|kil[oó]metr\w*)?\.?\s*"
    r"(?:в|al|a|per|/|за)\s*(месяц|mes|month|год|año|ano|year)",
    re.I,
)


_PERIOD_MONTH = ("месяц", "mes", "month")


def _num(s: str) -> float:
    s = s.replace(" ", " ").strip()
    if _THOUSANDS.fullmatch(s):
        return float(_GROUP_SEP.sub("", s))
    return float(s.replace(",", "."))


def parse_distance(text: str | None) -> tuple[int, int] | None:
    """A yearly distance (min, max) in km from the user's words, or None. A mileage without a period is not it."""
    if not text:
        return None
    m = _DIST.search(text)
    if not m:
        return None
    lo = _num(m.group(1))
    hi = _num(m.group(2)) if m.group(2) else lo
    mult = 1000.0 if m.group(3) else 1.0
    per_year = 12.0 if m.group(4).lower() in _PERIOD_MONTH else 1.0
    a, b = round(lo * mult * per_year), round(hi * mult * per_year)
    if not (1000 <= a <= 200000 and 1000 <= b <= 200000):
        return None
    return (min(a, b), max(a, b))
