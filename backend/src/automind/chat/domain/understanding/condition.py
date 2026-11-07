"""New or used, from the person words (spec 005)."""

from __future__ import annotations

import re

from automind.chat.domain.case.enums import Condition

_NEW = re.compile(r"\b(нов\w*|new|nuev\w*|0 ?km|с нуля|из салона)\b", re.I)


_USED = re.compile(
    r"(подержан\w*|\bб/у\b|\bбу\b|с пробегом|\bused\b|second[- ]hand|segunda mano|ocasi[oó]n|seminuev\w*)", re.I
)


def condition_of(text: str | None) -> Condition | None:
    """NEW / USED from a short answer ("новые", "б/у", "de segunda mano"); None when the text says neither."""
    if not text:
        return None
    used, new = bool(_USED.search(text)), bool(_NEW.search(text))
    if used == new:
        return None
    return "USED" if used else "NEW"
