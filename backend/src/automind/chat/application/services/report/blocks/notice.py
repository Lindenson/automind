"""Block notice: a short message shown with the report or the turn (info or warning)."""

from __future__ import annotations

from typing import Any


def notice(text: str, level: str = "info", **about: str) -> dict[str, Any]:
    """`about` (car_key, area) lets a later step drop a notice that another one explains better."""
    return {"type": "notice", "level": level, "text": text, **about}
