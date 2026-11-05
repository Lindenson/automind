"""Grouping failures into issues (spec 010 US3, research R6). Pure.

A failure has a key `component/class/...`; failures with the same key form one group. A group becomes an issue when
it has at least the component's threshold of failures in the last 7 days. The fingerprint is stable across runs, so
the same problem is one issue, not one per run.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

DEFAULT_THRESHOLD = 3


@dataclass(frozen=True)
class Failure:
    component: str
    klass: str
    key: str
    at: datetime
    chat_id: str | None = None
    turn_id: str | None = None
    quote: str | None = None
    url: str | None = None
    claim_id: str | None = None


@dataclass
class Group:
    key: str
    component: str
    klass: str
    count_total: int
    count_7d: int
    chats_7d: int
    first_seen: datetime
    last_seen: datetime
    examples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.key)


def fingerprint(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()  # noqa: S324 - an identifier, not security


def _example(f: Failure) -> dict[str, Any]:
    out = {
        "chat_id": f.chat_id,
        "turn_id": f.turn_id,
        "quote": (f.quote or "")[:400],
        "url": f.url,
        "claim_id": f.claim_id,
        "at": f.at.isoformat(),
    }
    return {k: v for k, v in out.items() if v}


def group(failures: Iterable[Failure], thresholds: Mapping[str, int], now: datetime, examples: int = 10) -> list[Group]:
    by_key: dict[str, list[Failure]] = defaultdict(list)
    for f in failures:
        by_key[f.key].append(f)
    week = now - timedelta(days=7)
    out: list[Group] = []
    for key, fs in by_key.items():
        fs.sort(key=lambda x: x.at, reverse=True)
        recent = [f for f in fs if f.at >= week]
        if len(recent) < int(thresholds.get(fs[0].component, DEFAULT_THRESHOLD)):
            continue
        out.append(
            Group(
                key=key,
                component=fs[0].component,
                klass=fs[0].klass,
                count_total=len(fs),
                count_7d=len(recent),
                chats_7d=len({f.chat_id for f in recent if f.chat_id}),
                first_seen=fs[-1].at,
                last_seen=fs[0].at,
                examples=[_example(f) for f in fs[:examples]],
            )
        )
    out.sort(key=lambda g: (g.count_7d, g.last_seen), reverse=True)
    return out
