"""Impact of an issue and the top list (spec 010 US4, research R15). Pure."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol


class _Grouped(Protocol):
    klass: str
    count_7d: int
    chats_7d: int


def impact(g: _Grouped, severity: Mapping[str, float], chat_weight: float = 2.0) -> float:
    """Failing turns in 7 days × class severity + chat_weight × chats affected."""
    return float(g.count_7d) * float(severity.get(g.klass, 1)) + chat_weight * float(g.chats_7d)


def top[T: _Grouped](
    groups: Iterable[T], severity: Mapping[str, float], chat_weight: float = 2.0, n: int = 10
) -> list[T]:
    return sorted(groups, key=lambda g: impact(g, severity, chat_weight), reverse=True)[:n]
