"""Number guard (FR-031): every number in AI-written text must exist in validated or computed data."""

from __future__ import annotations

import json
import re
from typing import Any

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Numbers inside model codes (J250, Mk8, F30, i30, D-4D) are names, not figures: not checked.
_CHECKED_RE = re.compile(r"(?<![A-Za-z])(?<![A-Za-z]-)(?<![\d.,])\d+(?:[.,]\d+)?")
ALWAYS_OK = {0.0, 100.0, 200.0, 400.0, 62.0, 60.0}  # 0-100 km/h, 0-200, 400 m, 0-62 mph


def _to_float(n: str) -> float:
    return float(n.replace(",", "."))


def numbers_in(obj: Any) -> set[float]:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return {_to_float(n) for n in _NUM_RE.findall(text)}


def _ok(x: float, allowed: set[float]) -> bool:
    if x in ALWAYS_OK or (x.is_integer() and (x <= 12 or 1950 <= x <= 2035)):
        return True
    return any(abs(x - a) <= max(0.051, 0.005 * abs(a)) for a in allowed)


def check_numbers(text: str, allowed: set[float]) -> tuple[str, int]:
    """Drop sentences containing numbers not present in the allowed data. Returns (text, dropped)."""
    kept, dropped = [], 0
    for line in text.split("\n"):
        good = []
        for p in re.split(r"(?<=[.!?])\s+", line):
            if all(_ok(_to_float(n), allowed) for n in _CHECKED_RE.findall(p)):
                good.append(p)
            else:
                dropped += 1
        kept.append(" ".join(good))
    return "\n".join(kept).strip(), dropped


def removal_notice(dropped: int) -> dict[str, str]:
    return {
        "type": "notice",
        "level": "info",
        "text": f"{dropped} sentence(s) removed by the number check (numbers not found in validated data).",
    }
