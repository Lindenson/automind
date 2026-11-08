"""A stored parser version as the readers see it (spec 011 data-model "Migration 0022"), and the sentence that
explains its degradation. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from automind.acquisition.domain.drift import Drift
from automind.acquisition.parsing.readers.spec import ParserSpec
from automind.shared.provenance.versions import parse_key

RUNNING = ("active", "degraded")  # a degraded version keeps running until a replacement is accepted (R12)


@dataclass(frozen=True)
class Version:
    """One parser version: its key (`km77@v1`), spec, status and pages in a row with no field."""

    key: str
    spec: ParserSpec
    status: str
    zero_streak: int = 0


def explanation(key: str, drift: Drift, since: datetime | None = None) -> str:
    """One sentence with the numbers, built by code: "km77 parser v1 degraded: 5 pages in a row with no fields since
    2026-11-05 10:02 UTC"."""
    reader, n = parse_key(key)
    tail = f" since {since.astimezone(UTC):%Y-%m-%d %H:%M} UTC" if since is not None else ""
    return f"{reader} parser v{n} degraded: {drift.reason}{tail}"
