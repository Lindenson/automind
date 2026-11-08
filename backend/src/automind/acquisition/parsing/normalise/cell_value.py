"""The raw number and unit of a spec table cell (spec 003 FR-009), before the domain unit layer converts them.

"190 CV / 140 kW" → ("190", "CV"); "1540 kg3395 lbs." → ("1540", "kg"); a range "4.2-4.5 l/100 km" stays whole (the unit
layer rejects it as not one value); a text field (gearbox, drivetrain) keeps the cell as it is.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_NUM = r"(\d[\d.,]*)"
_CUBIC = re.compile(r"\b(cm|m|dm) ([23])\b")  # "cm<sup>3</sup>" read with a separator: "cm 3"
_RANGE = re.compile(r"\s*" + _NUM + r"\s*[-–]\s*\d")  # "4.2-4.5"
_VALUE = re.compile(r"\s*" + _NUM + r"\s*([A-Za-z³²µ°%]+(?:/[0-9]*\s?[A-Za-z]*)?)?")  # "190 CV", "6,2 l/100km"


def value_and_unit(text: str, hints: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """(raw number, unit) of a cell, or None without a number. `hints`: `unit` forces the unit, `prefer_unit` takes
    the number before that unit when the cell lists several, `text` keeps the whole cell as the value."""
    t = _CUBIC.sub(r"\1\2", " ".join(text.replace("\xa0", " ").split()))
    if hints.get("text"):
        return t, None
    if pu := hints.get("prefer_unit"):
        m = re.search(_NUM + r"\s*" + re.escape(str(pu)), t, re.I)  # the unit comes from the spec, not a literal
        if m:
            return m.group(1), str(hints.get("unit") or pu)
    if _RANGE.match(t):
        return t, hints.get("unit")
    m = _VALUE.match(t)
    if not m:
        return None
    unit = hints.get("unit") or ((m.group(2) or "").strip(". ") or None)
    return m.group(1), (str(unit) if unit else None)
