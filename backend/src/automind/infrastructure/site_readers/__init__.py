"""Deterministic table readers for favourite spec sites (spec 003 FR-009, research R6).

A reader runs only for favourites whose `reader` is set and whose `tos_checked` date is set
(the operator reviewed the site's terms). Readers are filled in by US1 (T031).
"""

from __future__ import annotations

from typing import Any

from automind.application.ports import Page, SiteReading


class Registry:
    def __init__(self, readers: dict[str, Any] | None = None, enabled: dict[str, str] | None = None) -> None:
        self.readers = readers or {}  # reader id -> callable(html, url, target) -> SiteReading | None
        self.enabled = enabled or {}  # domain -> reader id (favourites with tos_checked)

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        return None


def live_readers() -> Registry:
    return Registry()
