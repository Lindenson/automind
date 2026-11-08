"""spec 012 A3c: the live site readers over their ports (fakes, no database) — refresh, flush and the zero streak."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from automind.acquisition.domain.drift import Drift, DriftConfig
from automind.acquisition.parsing.readers.migrate_v1 import migrate_v1
from automind.acquisition.parsing.readers.ports import ParserStoreUnavailable
from automind.acquisition.parsing.readers.registry import ParserRegistry
from automind.acquisition.parsing.readers.versions import Version
from automind.shared.contracts.web import Page

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "html"
KM77_HTML = (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8")
SPEC = migrate_v1(
    "km77", {"domains": ["km77.com"], "labels": {"Potencia máxima": {"attribute": "power_kw", "unit": "kW"}}}
)
EMPTY = "<html><body><p>nothing</p></body></html>"


class Book:
    def __init__(self, versions: list[Version] | None = None, down: bool = False) -> None:
        self.versions, self.down = versions or [], down
        self.streak = 0
        self.degraded: list[tuple[str, str]] = []

    async def running(self) -> list[Version]:
        if self.down:
            raise ParserStoreUnavailable("running: OperationalError")
        return self.versions

    async def allowed_domains(self, domains: list[str]) -> set[str]:
        return set(domains)

    async def add_zero_streak(self, key: str, zeros: int, reset: bool) -> tuple[int, str] | None:
        self.streak = zeros if reset else self.streak + zeros
        return self.streak, "active"

    async def degrade(self, key: str, drift: Drift, *, since: datetime | None = None,
                      evidence: dict[str, Any] | None = None) -> str | None:  # fmt: skip
        self.degraded.append((key, drift.reason))
        return "change-1"


class Log:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.stats: list[Mapping[Any, Any]] = []
        self.stamps: list[Mapping[str, Any]] = []

    async def add_site_stats(self, counts: Mapping[Any, Mapping[str, int]]) -> None:
        if self.down:
            raise ParserStoreUnavailable("add_site_stats: OperationalError")
        self.stats.append(counts)

    async def stamp_snapshots(self, stamps: Mapping[str, Any]) -> None:
        self.stamps.append(stamps)


class Shadow:
    def __init__(self) -> None:
        self.read: list[Mapping[str, str]] = []

    async def notify_read(self, read: Mapping[str, str]) -> None:
        self.read.append(read)


def _page(n: int, html: str, sid: str | None = None) -> Page:
    return Page(url=f"https://www.km77.com/coches/{n}/datos", title="t", text="", html=html, snapshot_id=sid)


async def test_store_down_on_refresh_keeps_the_readers_it_has():
    reg = ParserRegistry(Book(down=True), Log(), Shadow(), [SPEC], live=True)
    await reg.refresh()
    assert not reg.from_db and reg.version_for("https://www.km77.com/x") == SPEC


async def test_a_failed_flush_step_is_dropped_and_the_next_steps_still_run():
    log, shadow = Log(down=True), Shadow()
    reg = ParserRegistry(Book(), log, shadow, [SPEC])
    reg.read(_page(1, KM77_HTML, sid="s1"), {})
    await reg.flush_stats()
    assert log.stats == [] and reg.tally.stats == {}  # site counts lost with the store, the job goes on
    assert list(log.stamps[0]) == ["s1"] and shadow.read == [{"s1": "km77@v1"}]


async def test_zero_streak_at_the_limit_degrades_the_stored_version():
    book = Book([Version(SPEC.key, SPEC, "active")])
    reg = ParserRegistry(book, Log(), Shadow(), live=True, cfg=DriftConfig(zero_streak=3))
    await reg.refresh()
    for i in range(2):
        reg.read(_page(i, EMPTY), {})
    await reg.flush_stats()
    assert book.streak == 2 and book.degraded == []
    reg.read(_page(3, EMPTY), {})
    await reg.flush_stats()
    assert book.degraded == [("km77@v1", "3 pages in a row with no fields")]
    assert reg.by_domain["km77.com"].status == "degraded"
