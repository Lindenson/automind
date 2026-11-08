"""Accuracy signals without the user (spec 011 FR-010/FR-011, research R7-R9, T070): read after the fact from what
research stored, so the pipeline needs no hook. For each version: its facts are loaded, the rules find the signals
(`domain.findings`: gold and fusion, physics, agreement, replacement), every wrong one gets its blame vector from the
claim's excerpt and stored page, and each is sent to the registry once. A disputed one is applied only after the
`blame_judge` task settles it: `scan` queues those tasks.

Errors: a store failure (`ReputationStoreUnavailable`) while loading a version's facts propagates; a rule kind that
fails is logged and the other kinds still run (one bad attribute never silences the rest); a page that is gone is
read as the claim's cached text."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from automind.acquisition.domain.tolerance import Tolerance
from automind.acquisition.registry.api import TruthSignalIn
from automind.acquisition.reputation.domain import findings as rules
from automind.acquisition.reputation.domain.signal_facts import ClaimFact, Finding, VariantFacts
from automind.shared.contracts.json import JsonObject

log = logging.getLogger(__name__)
LOOKBACK = timedelta(hours=26)  # a day and a margin: a daily scan never misses a version


class SignalFacts(Protocol):
    """What research stored, as the rules read it. Raises `ReputationStoreUnavailable`."""

    async def facts(self, variant_id: str) -> VariantFacts | None:
        """The version's facts, None when the version is gone."""
        ...

    async def recent_variants(self, since: datetime) -> list[str]:
        """Versions with an accepted claim, a selection or a gold value since `since` (new gold re-checks old
        claims)."""
        ...


class PageTexts(Protocol):
    """The stored pages (snapshots). Raises `ReputationStoreUnavailable`."""

    async def snapshot_text(self, snapshot_id: str) -> str | None:
        """The visible text of a stored page, None when it is gone."""
        ...


class Tolerances(Protocol):
    """How close a value must be to its truth, by attribute."""

    def of(self, attribute: str) -> Tolerance:
        """The attribute's tolerance (config/gold_datasets.yaml, else the attribute's own)."""
        ...


class SignalSink(Protocol):
    """The registry's truth signals."""

    async def signal(self, s: TruthSignalIn) -> str | None:
        """Record a signal (the registry); its id, None when it was already recorded."""
        ...


class JudgeQueue(Protocol):
    """The worker's queue of `blame_judge` tasks."""

    async def judge(self, signal_ids: list[str]) -> int:
        """Queue a `blame_judge` task per disputed signal; returns how many were queued."""
        ...


class Clock(Protocol):
    """The time of the system (a fixed one in tests)."""

    def now(self) -> datetime:
        """Now, timezone-aware."""
        ...


@dataclass
class Emitted:
    """Signals sent for a version, counted by kind (`gold_right`, `fusion`, …), and the disputed ones' ids."""

    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    disputed: list[str] = field(default_factory=list)


class SignalScan:
    """The signals of the versions research touched, with the stores, the registry, the judge queue, the clock and
    the physics checks (`config/physics.yaml checks`)."""

    def __init__(self, facts: SignalFacts, pages: PageTexts, tolerances: Tolerances, sink: SignalSink,
                 judges: JudgeQueue, clock: Clock, physics_checks: JsonObject) -> None:  # fmt: skip
        self.facts, self.pages, self.tolerances, self.sink = facts, pages, tolerances, sink
        self.judges, self.clock, self.physics_checks = judges, clock, physics_checks

    async def scan(self, variant_ids: list[str] | None = None, since: datetime | None = None,
                   judge: bool = True) -> dict[str, int]:  # fmt: skip
        """The worker's `reputation_signals` task: the given versions, or those touched since `since` (a day ago).
        Returns the counts by kind plus `variants`, `disputed` and, when `judge`, `judge_tasks` queued."""
        ids = variant_ids if variant_ids is not None else await self.facts.recent_variants(
            since or self.clock.now() - LOOKBACK)  # fmt: skip
        total: dict[str, int] = defaultdict(int)
        disputed: list[str] = []
        for vid in ids:
            e = await self.for_variant(vid)
            for k, n in e.counts.items():
                total[k] += n
            disputed += e.disputed
        total["variants"], total["disputed"] = len(ids), len(disputed)
        if judge and disputed:
            total["judge_tasks"] = await self.judges.judge(disputed)
        return dict(total)

    async def for_variant(self, variant_id: str) -> Emitted:
        """Every kind of signal for one version, each sent once."""
        out = Emitted()
        f = await self.facts.facts(variant_id)
        if f is None:
            return out
        tols = {a: self.tolerances.of(a) for a in f.attributes()}
        kinds: list[tuple[str, Callable[[], list[Finding]]]] = [
            ("gold", lambda: rules.gold_findings(f, tols)),
            ("fusion", lambda: rules.fusion_findings(f, tols)),
            ("physics", lambda: rules.physics_findings(f, tols, self.physics_checks)),
            ("agreement", lambda: rules.agreement_findings(f, tols)),
            ("replacement", lambda: rules.replacement_findings(f, tols)),
        ]
        pages: dict[str, str] = {}
        for name, find in kinds:
            try:
                for finding in find():
                    await self._send(f, finding, pages, out)
            except Exception:  # noqa: BLE001 - one failing kind never stops the others (module docstring)
                log.exception("reputation.%s_failed variant=%s", name, variant_id)
        return out

    async def _send(self, f: VariantFacts, finding: Finding, pages: dict[str, str], out: Emitted) -> None:
        signal = await self._signal_in(f, finding, pages)
        sid = await self.sink.signal(signal)
        if sid is None:
            return
        out.counts[finding.counter] += 1
        if signal.disputed:
            out.disputed.append(sid)

    async def _signal_in(self, f: VariantFacts, x: Finding, pages: dict[str, str]) -> TruthSignalIn:
        c = x.claim
        fields: JsonObject = {"kind": x.kind, "verdict": x.verdict, "domain": c.domain if c else x.domain,
                              "area": c.area if c else x.area, "variant_id": f.id, "attribute": x.attribute,
                              "details": x.details}  # fmt: skip
        if c is not None:
            fields |= {"claim_id": c.id, "snapshot_id": c.snapshot_id}
        if x.gold_id is not None:
            fields["gold_id"] = x.gold_id
        if x.fixed_blame is not None:
            fields |= {"blame_vector": x.fixed_blame[0], "components": x.fixed_blame[1]}
        elif x.blame is not None and c is not None:
            text = await self._page(c, pages) if x.blame.truth is not None else c.doc_text
            vector, components, disputed = rules.blamed(f, c, x.blame, text)
            fields |= {"blame_vector": vector, "components": components, "disputed": disputed}
        return TruthSignalIn.model_validate(fields)

    async def _page(self, c: ClaimFact, pages: dict[str, str]) -> str:
        """The claim's cached text plus its stored page, read once per page."""
        key = c.snapshot_id or f"doc:{c.doc_id}"
        if key not in pages:
            stored = await self.pages.snapshot_text(c.snapshot_id) if c.snapshot_id else None
            pages[key] = f"{c.doc_text}\n{stored}" if stored is not None else c.doc_text
        return pages[key]
