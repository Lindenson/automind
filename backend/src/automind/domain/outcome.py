"""Outcome of a turn (spec 010 US1, research R3). Pure.

A turn gets failure classes and a score from 0 to 1. An explicit rating wins (1 → 0, 5 → 1). Otherwise the score
starts at a configured value and each present signal adds its configured weight; the result is clamped. Signals
are presence-based (one wrong value or three both count once), so one noisy turn cannot dominate an index.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FailureClass(StrEnum):
    NOT_UNDERSTOOD = "not_understood"
    WRONG_CAR = "wrong_car"
    NO_DATA = "no_data"
    WRONG_DATA = "wrong_data"
    BAD_TEXT = "bad_text"
    PROCESS_FAILURE = "process_failure"
    TOO_COSTLY = "too_costly"


RELATIONS = ("continues", "rephrase", "correction", "complaint", "thanks", "new_topic")
FAILED_STATUSES = ("FAILED",)


@dataclass(frozen=True)
class TurnFacts:
    status: str
    action: str | None = None
    relation_next: str | None = None  # how the next user message relates to this turn's answer
    rating: int | None = None  # 1..5
    signals: Mapping[str, float] = field(default_factory=dict)  # counts: wrong_value, no_data, guard_removed, ...


def _has(f: TurnFacts, key: str) -> bool:
    return float(f.signals.get(key, 0) or 0) > 0


def classes(f: TurnFacts) -> set[FailureClass]:
    out: set[FailureClass] = set()
    if f.relation_next in ("rephrase", "correction"):
        out.add(FailureClass.NOT_UNDERSTOOD)
    if _has(f, "wrong_car"):
        out.add(FailureClass.WRONG_CAR)
    if _has(f, "no_data"):
        out.add(FailureClass.NO_DATA)
    if _has(f, "wrong_value") or _has(f, "bad_source"):
        out.add(FailureClass.WRONG_DATA)
    if _has(f, "guard_removed") or f.relation_next == "complaint" or _has(f, "complaint"):
        out.add(FailureClass.BAD_TEXT)
    if f.status in FAILED_STATUSES or _has(f, "process_failure"):
        out.add(FailureClass.PROCESS_FAILURE)
    if _has(f, "too_costly"):
        out.add(FailureClass.TOO_COSTLY)
    return out


def score(f: TurnFacts, cfg: Mapping[str, Any]) -> float:
    if f.rating is not None and cfg.get("rating_wins", True):
        r = min(5, max(1, int(f.rating)))
        return (r - 1) / 4
    w: Mapping[str, float] = cfg.get("weights") or {}
    s = float(cfg.get("start", 0.6))
    present: set[str] = {k for k, v in f.signals.items() if float(v or 0) > 0}
    if f.relation_next in RELATIONS:
        present.add(f.relation_next)
    if f.status in FAILED_STATUSES:
        present.add("process_failure")
    if f.action == "REPORT" and f.status not in FAILED_STATUSES:
        present.add("report_reached")
    for key in present:
        s += float(w.get(key, 0.0))
    return round(min(1.0, max(0.0, s)), 4)
