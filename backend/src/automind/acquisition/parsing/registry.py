"""The live site readers (spec 011 T087): the running parser spec version per domain, read by the fixed interpreter.

Versions come from the database (`parsers.active_version`, status active or degraded), refreshed every 60 s before a
job reads its pages; with no parser in the database (or no database) the version-1 specs of config/site_readers.yaml
are used. A reader runs only for domains whose registry source has access "ok" (the YAML fallback keeps the old rule:
favourites with a reviewed reader). Per page the adapter
- returns the rows as a `SiteReading` named by the version key (`km77@v1`), or None below `min_rows`;
- stores the page's structure fingerprint and the version on its snapshot (`page_snapshots.structure_hash`,
  `parser_version`);
- keeps the version's zero streak (pages in a row with no field); at `drift.zero_streak` an active version is
  degraded at once, journalled and handed to the parser doctor (research R12);
- still counts ok/failed/ambiguous per site and day in `site_reader_stats` (dropped in a later spec).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from automind.acquisition.domain import drift
from automind.acquisition.parsing import fingerprint, interpreter
from automind.acquisition.parsing.spec import ParserSpec
from automind.application.ports import Page, ReadingRow, SiteReading
from automind.domain.evidence import domain_of

log = logging.getLogger(__name__)
REFRESH_S = 60.0
STREAKS: dict[str, int] = {}  # reader -> pages in a row with no field, in this process (automind_reader_zero_streak)


@dataclass
class _Running:
    spec: ParserSpec
    status: str = "active"
    labels: list[str] = field(default_factory=list)


@dataclass
class _Streak:
    zeros: int = 0  # pages with no field since the last flush (after `reset`)
    reset: bool = False  # a page had fields since the last flush
    since: datetime | None = None  # first page of the current streak
    total: int = 0  # the streak as this process sees it


def _matches(domain: str, d: str) -> bool:
    return domain == d or domain.endswith("." + d)


class ParserRegistry:
    """`SiteReaders` port over versioned parser specs."""

    def __init__(self, specs: Iterable[ParserSpec] = (), *, allowed: Iterable[str] | None = None,
                 live: bool = False, cfg: drift.DriftConfig | None = None) -> None:  # fmt: skip
        self.live = live
        self.cfg = cfg or drift.DriftConfig()
        self.from_db = False
        self._loaded_at = 0.0
        self._set([(s, "active") for s in specs], allowed)
        self.stats: dict[tuple[str, str], dict[str, int]] = {}
        self.streaks: dict[str, _Streak] = {}
        self.snapshots: dict[str, tuple[str, str]] = {}  # snapshot id -> (structure hash, version key)

    # --- versions ---------------------------------------------------------------------------------------------

    def _set(self, versions: list[tuple[ParserSpec, str]], allowed: Iterable[str] | None) -> None:
        allow = None if allowed is None else {d.lower() for d in allowed}
        self.by_domain: dict[str, _Running] = {}
        for spec, status in versions:
            run = _Running(spec, status, fingerprint.spec_labels(spec))
            for d in spec.domains:
                if allow is None or d in allow:
                    self.by_domain[d] = run

    @classmethod
    def from_yaml(cls, favourites: list[Mapping[str, Any]] | None = None, **kw: Any) -> ParserRegistry:
        """Version 1 of today's readers; with `favourites`, only for those with a reader whose terms were reviewed.
        Deny-listed readers (auto_data) never run."""
        from automind.acquisition.parsing.migrate_v1 import denied, denylist, yaml_specs  # noqa: PLC0415

        deny = denylist()
        specs = [s for s in yaml_specs().values() if not denied(s, deny)]
        allowed = None
        if favourites is not None:
            allowed = [str(f["domain"]) for f in favourites if f.get("reader") and f.get("tos_checked")]
        return cls(specs, allowed=allowed, **kw)

    @classmethod
    def live_registry(cls) -> ParserRegistry:
        from automind.infrastructure.config import acquisition_config, favourites  # noqa: PLC0415

        cfg = drift.DriftConfig.from_mapping(acquisition_config().get("drift"))
        return cls.from_yaml(favourites(), live=True, cfg=cfg)

    async def refresh(self) -> None:
        """Load the running versions from the database; keep the YAML v1 readers when it has none."""
        from automind.acquisition.parsing import store  # noqa: PLC0415

        self._loaded_at = time.monotonic()
        try:
            versions = await store.running()
            if not versions:
                return
            allowed = await store.allowed_domains(sorted({d for v in versions for d in v.spec.domains}))
        except Exception:  # noqa: BLE001 - the database may be restarting: keep the readers we have
            log.warning("parser_registry.refresh_failed", exc_info=True)
            return
        self._set([(v.spec, v.status) for v in versions], allowed)
        self.from_db = True

    async def prepare(self) -> None:
        """Called before a job reads its pages: refresh every REFRESH_S seconds (live registries only)."""
        if self.live and time.monotonic() - self._loaded_at >= REFRESH_S:
            await self.refresh()

    def version_for(self, url: str) -> ParserSpec | None:
        dom = domain_of(url)
        run = next((r for d, r in self.by_domain.items() if _matches(dom, d)), None)
        return run.spec if run is not None else None

    # --- reading ----------------------------------------------------------------------------------------------

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        dom = domain_of(page.url)
        run = next((r for d, r in self.by_domain.items() if _matches(dom, d)), None)
        if run is None or not page.html:
            return None
        spec = run.spec
        if spec.url_patterns and not interpreter.applies(spec, page.url):
            return None
        try:
            got = interpreter.read_rows(spec, page.html, page.url)
        except Exception:  # noqa: BLE001 - a broken page never fails the job
            got = interpreter.Reading(spec.key)
        out = None
        if len(got.rows) >= spec.min_rows:
            rows = [ReadingRow(r.attribute, r.raw_value, r.raw_unit, r.excerpt) for r in got.rows]
            out = SiteReading(reader=spec.key, rows=rows, ambiguous=got.ambiguous)
        if page.snapshot_id:
            try:
                fp = fingerprint.structure(page.html, run.labels)
                self.snapshots[page.snapshot_id] = (fp.hash, spec.key)
            except Exception:  # noqa: BLE001
                log.debug("parser_registry.fingerprint_failed", exc_info=True)
        self._count(dom, spec, out, len(got.rows))
        return out

    def _count(self, dom: str, spec: ParserSpec, out: SiteReading | None, fields: int) -> None:
        day = datetime.now(UTC).date().isoformat()
        s = self.stats.setdefault((dom, day), {"ok": 0, "failed": 0, "ambiguous": 0})
        s["failed" if out is None else "ambiguous" if out.ambiguous else "ok"] += 1
        st = self.streaks.setdefault(spec.key, _Streak())
        if fields:
            st.zeros, st.reset, st.since, st.total = 0, True, None, 0
        else:
            st.zeros += 1
            st.total += 1
            st.since = st.since or datetime.now(UTC)
        STREAKS[spec.reader] = st.total
        if st.total == self.cfg.zero_streak:  # a redesign breaks label readers silently: say it once
            log.warning("site_reader.broken reader=%s domain=%s pages_in_a_row=%d", spec.key, dom, st.total,
                        extra={"event": "site_reader.broken", "reader": spec.key, "domain": dom})  # fmt: skip

    # --- persistence ------------------------------------------------------------------------------------------

    async def flush_stats(self) -> None:
        """Write what the reads counted: site_reader_stats, snapshot fingerprints, zero streaks (and degrade)."""
        for step in (self._flush_site_stats, self._flush_snapshots, self._flush_streaks):
            try:
                await step()
            except Exception:  # noqa: BLE001 - bookkeeping never fails the job
                log.warning("parser_registry.flush_failed step=%s", step.__name__, exc_info=True)

    async def _flush_site_stats(self) -> None:
        if not self.stats:
            return
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from automind.infrastructure.db import SiteReaderStat, sessionmaker  # noqa: PLC0415

        pending, self.stats = self.stats, {}
        async with sessionmaker()() as s:
            for (domain, day), n in pending.items():
                stmt = insert(SiteReaderStat).values(domain=domain, day=datetime.fromisoformat(day).date(), **n)
                await s.execute(stmt.on_conflict_do_update(
                    index_elements=["domain", "day"],
                    set_={k: getattr(SiteReaderStat, k) + stmt.excluded[k] for k in n},
                ))  # fmt: skip
            await s.commit()

    async def _flush_snapshots(self) -> None:
        if not self.snapshots:
            return
        from sqlalchemy import update  # noqa: PLC0415

        from automind.infrastructure.db import PageSnapshot, sessionmaker  # noqa: PLC0415

        pending, self.snapshots = self.snapshots, {}
        async with sessionmaker()() as s:
            for sid, (h, key) in pending.items():
                await s.execute(update(PageSnapshot).where(PageSnapshot.id == sid)
                                .values(structure_hash=h, parser_version=key))  # fmt: skip
            await s.commit()

    async def _flush_streaks(self) -> None:
        if not self.from_db:
            return  # the YAML fallback has no stored versions to keep a streak on
        from automind.acquisition.parsing import store  # noqa: PLC0415

        for key, st in list(self.streaks.items()):
            if not st.zeros and not st.reset:
                continue
            zeros, reset, since = st.zeros, st.reset, st.since
            st.zeros, st.reset = 0, False
            got = await store.add_zero_streak(key, zeros, reset)
            if got is None:
                continue
            streak, status = got
            verdict = drift.zero_streak(streak, self.cfg)
            if verdict is not None and status == "active":
                await store.degrade(key, verdict, since=since, evidence={"zero_streak": streak})
                for run in self.by_domain.values():
                    if run.spec.key == key:
                        run.status = "degraded"


def live_readers() -> ParserRegistry:
    return ParserRegistry.live_registry()
