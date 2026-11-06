"""Deterministic site readers' output (spec 003 FR-009): rows read from a known site's page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from automind.shared.contracts.web import Page


@dataclass(frozen=True)
class ReadingRow:
    attribute: str
    raw_value: str
    raw_unit: str | None
    excerpt: str  # the table row text, so the 002 excerpt validation still applies


@dataclass(frozen=True)
class SiteReading:
    reader: str
    rows: list[ReadingRow]
    ambiguous: bool = False


class SiteReaders(Protocol):
    """Deterministic table readers for favourite spec sites (spec 003 R6). None = layout not recognised."""

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None: ...


class NoReaders:
    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        return None
