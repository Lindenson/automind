"""Numbers as spec pages write them, read before the unit layer (spec 004 FR-027: the boot volume check)."""

from __future__ import annotations

import re

_NUMBER = re.compile(r"\d[\d.,  ]*")  # "1.642", "611 l", "1 642"
_THOUSANDS = re.compile(r"\d{1,2}[.,]\d{3}")  # "1.642" (Spanish thousands), never "6,2"
_SEPARATORS = re.compile(r"[.,  ]")


def litres(raw: str) -> float | None:
    """ "611", "1.642" (Spanish thousands) or "611 l" as litres; None when there is no number."""
    m = _NUMBER.search(raw or "")
    if not m:
        return None
    digits = _SEPARATORS.sub("", m.group(0)) if _THOUSANDS.fullmatch(m.group(0).strip()) else m.group(0)
    try:
        return float(digits.strip().replace(",", "."))
    except ValueError:
        return None
