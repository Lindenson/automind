"""The live site readers (spec 011 T087): the running parser spec version per domain, read by the fixed interpreter.

Versions come from the parser book (`parsers.active_version`, status active or degraded), refreshed every 60 s before
a job reads its pages; with no parser in the book (or the book unavailable) the version-1 specs it was built with are
used (`wiring.yaml_registry`). A reader runs only for domains whose registry source has access "ok" (the YAML
fallback keeps the old rule: favourites with a reviewed reader). Per page the registry
- returns the rows as a `SiteReading` named by the version key (`km77@v1`), or None below `min_rows`;
- tallies the page's structure fingerprint and version for its snapshot, the site's ok/failed/ambiguous count, and
  the version's zero streak (`tally.py`).
`flush_stats()` writes the tally: site counts, snapshot stamps (then the shadow gate's feed), and the streaks — at
`drift.zero_streak` an active version is degraded at once, journalled and handed to the parser doctor (research R12).
Errors: a failed refresh keeps the readers it has; a failed flush step is logged and dropped (bookkeeping never
fails a job).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from automind.acquisition.domain import drift
from automind.acquisition.parsing.readers import fingerprint, interpreter
from automind.acquisition.parsing.readers.ports import ParserBook, ParserStoreUnavailable, ReadingLog, ReadShadow
from automind.acquisition.parsing.readers.spec import ParserSpec
from automind.acquisition.parsing.readers.tally import ReadingTally
from automind.shared.contracts.site_readers import ReadingRow, SiteReading
from automind.shared.contracts.web import Page
from automind.shared.evidence import domain_of

log = logging.getLogger(__name__)
REFRESH_S = 60.0


@dataclass
class Running:
    """The version a domain runs, with its labels for the fingerprint."""

    spec: ParserSpec
    status: str = "active"
    labels: list[str] = field(default_factory=list)


class ParserRegistry:
    """`SiteReaders` port over versioned parser specs."""

    def __init__(self, book: ParserBook, reads: ReadingLog, shadow: ReadShadow, specs: Iterable[ParserSpec] = (), *,
                 allowed: Iterable[str] | None = None, live: bool = False,
                 cfg: drift.DriftConfig | None = None) -> None:  # fmt: skip
        """`specs` (allowed to `allowed` domains) run until the book has versions; `live` refreshes from the book."""
        self.book, self.reads, self.shadow = book, reads, shadow
        self.live = live
        self.cfg = cfg or drift.DriftConfig()
        self.from_db = False
        self._loaded_at = 0.0
        self.by_domain: dict[str, Running] = {}
        self._set([(s, "active") for s in specs], allowed)
        self.tally = ReadingTally(broken_at=self.cfg.zero_streak)

    async def refresh(self) -> None:
        """Load the running versions from the book; keep the readers we have when it has none or is unavailable."""
        self._loaded_at = time.monotonic()
        try:
            versions = await self.book.running()
            if not versions:
                return
            allowed = await self.book.allowed_domains(sorted({d for v in versions for d in v.spec.domains}))
        except ParserStoreUnavailable:  # the database may be restarting: keep the readers we have
            log.warning("parser_registry.refresh_failed", exc_info=True)
            return
        self._set([(v.spec, v.status) for v in versions], allowed)
        self.from_db = True

    async def prepare(self) -> None:
        """Called before a job reads its pages: refresh every REFRESH_S seconds (live registries only)."""
        if self.live and time.monotonic() - self._loaded_at >= REFRESH_S:
            await self.refresh()

    def version_for(self, url: str) -> ParserSpec | None:
        """The spec that reads this address's domain, if any."""
        run = self._running(domain_of(url))
        return run.spec if run is not None else None

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        """The page's rows by its domain's running version, or None (no reader, no HTML, other page, too few rows)."""
        dom = domain_of(page.url)
        run = self._running(dom)
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
            self._stamp(page.snapshot_id, page.html, run)
        self.tally.count(dom, spec.key, spec.reader, out, len(got.rows))
        return out

    async def flush_stats(self) -> None:
        """Write what the reads counted: site counts, snapshot stamps (and the shadow feed), zero streaks (degrade)."""
        for step in (self._flush_site_stats, self._flush_snapshots, self._flush_streaks):
            try:
                await step()
            except Exception:  # noqa: BLE001 - bookkeeping never fails the job (store or shadow gate down)
                log.warning("parser_registry.flush_failed step=%s", step.__name__, exc_info=True)

    def _set(self, versions: list[tuple[ParserSpec, str]], allowed: Iterable[str] | None) -> None:
        allow = None if allowed is None else {d.lower() for d in allowed}
        self.by_domain = {}
        for spec, status in versions:
            run = Running(spec, status, fingerprint.spec_labels(spec))
            for d in spec.domains:
                if allow is None or d in allow:
                    self.by_domain[d] = run

    def _running(self, dom: str) -> Running | None:
        return next((r for d, r in self.by_domain.items() if dom == d or dom.endswith("." + d)), None)

    def _stamp(self, snapshot_id: str, html: str, run: Running) -> None:
        try:
            fp = fingerprint.structure(html, run.labels)
            self.tally.snapshots[snapshot_id] = (fp.hash, run.spec.key)
        except Exception:  # noqa: BLE001
            log.debug("parser_registry.fingerprint_failed", exc_info=True)

    async def _flush_site_stats(self) -> None:
        if self.tally.stats:
            await self.reads.add_site_stats(self.tally.take_stats())

    async def _flush_snapshots(self) -> None:
        if not self.tally.snapshots:
            return
        pending = self.tally.take_snapshots()
        await self.reads.stamp_snapshots(pending)
        await self.shadow.notify_read({sid: key for sid, (_, key) in pending.items()})

    async def _flush_streaks(self) -> None:
        if not self.from_db:
            return  # the YAML fallback has no stored versions to keep a streak on
        for key, st in list(self.tally.streaks.items()):
            if not st.zeros and not st.reset:
                continue
            zeros, reset, since = st.take()
            got = await self.book.add_zero_streak(key, zeros, reset)
            if got is None:
                continue
            streak, status = got
            verdict = drift.zero_streak(streak, self.cfg)
            if verdict is not None and status == "active":
                await self.book.degrade(key, verdict, since=since, evidence={"zero_streak": streak})
                for run in self.by_domain.values():
                    if run.spec.key == key:
                        run.status = "degraded"
