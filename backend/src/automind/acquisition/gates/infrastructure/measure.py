"""Old and new versions of a change on the same stored pages (spec 011 US5, research R4): the measure the replay
gate, the shadow gate and the watch share. Per object kind: parser — the old and new specs offline; rule — every
running reader with the rules before and after (plausibility and sense; relevance keywords are `relevance_measure`);
prompt / role_model — the extractor with the old and new prompt or model (`measure_extractor`). Implements
`measure_ports.Measure`; a kind without a measure raises `NoMeasure`."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import select

from automind.acquisition.domain import gates
from automind.acquisition.domain import replay as scoring
from automind.acquisition.gates.application.measure_ports import Charge, MetricsPair, NoMeasure
from automind.acquisition.gates.domain.change import Change, corpus_window
from automind.acquisition.gates.infrastructure import page_reading as pages
from automind.acquisition.gates.infrastructure.measure_extractor import Pair, extractor_pair
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.infrastructure import overrides
from automind.acquisition.parsing import interpreter
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.contracts.llm import LLM
from automind.shared.evidence import sense
from automind.shared.infrastructure.config import loader as config
from automind.shared.infrastructure.db.models import PageSnapshot, ParserVersion
from automind.shared.infrastructure.db.session import sessionmaker

LIVE_PAGES = 200  # the watch reads at most this many of the new version's live pages


class PageMeasure:
    """The measures on stored pages."""

    async def corpus(self, c: Change, now: datetime) -> list[SnapshotRef]:
        """The pages the replay gate compares on: the parser's sites (the pages its new spec applies to), every
        running reader's sites for a rule, else pages about a version (at most `replay.extractor_max_pages`)."""
        since, until = corpus_window(c, now)
        if c.object_kind == "parser":
            old, new = await pages.spec_of(c.from_version), await pages.spec_of(c.to_version)
            domains = sorted({d for sp in (old, new) if sp is not None for d in sp.domains})
            refs = await pages.corpus_refs(domains, since, until)
            return [r for r in refs if new is None or interpreter.applies(new, r.final_url or r.url)]
        if c.object_kind == "rule":
            specs = await pages.running_specs()
            return await pages.corpus_refs(sorted({d for sp in specs for d in sp.domains}), since, until)
        cap = int((acq_config.acquisition_config().get("replay") or {}).get("extractor_max_pages", 60))
        refs = await pages.corpus_refs(None, since, until, limit=cap * 10)
        return [r for r in refs if r.variant_ids][:cap]

    async def refs(self, ids: list[str]) -> list[SnapshotRef]:
        """The stored pages with these ids."""
        return await pages.refs(ids)

    async def live_pages(self, c: Change, since: datetime) -> list[SnapshotRef]:
        """Pages the new parser version read since `since` (other kinds: none, they are judged on signals)."""
        if c.object_kind != "parser":
            return []
        async with sessionmaker()() as s:
            q = (select(PageSnapshot.id).where(PageSnapshot.parser_version == c.to_version,
                                               PageSnapshot.fetched_at >= since)
                 .order_by(PageSnapshot.fetched_at.desc()).limit(LIVE_PAGES))  # fmt: skip
            ids = [str(i) for (i,) in (await s.execute(q)).all()]
        return await pages.refs(ids)

    async def measure(self, c: Change, refs: list[SnapshotRef], *, since: datetime | None = None,
                      llm: LLM | None = None, charge: Charge | None = None) -> MetricsPair:  # fmt: skip
        """(old, new) metrics; yield over the pages fetched `since` when given. Raises `NoMeasure`."""
        if c.object_kind == "parser":
            old, new = await _parser_pair(c, refs)
        elif c.object_kind == "rule":
            old, new = await _rule_pair(c, refs)
        elif c.object_kind in ("prompt", "role_model"):
            old, new = await extractor_pair(c, refs, llm=llm, charge=charge)
        else:
            raise NoMeasure(f"no offline measure for {c.object_kind} changes")
        gold = await pages.gold_for(old + new)
        late = {r.id for r in refs if since is None or r.fetched_at >= since}

        def m(results: list[scoring.PageResult]) -> gates.Metrics:
            sub = [p for p in results if p.snapshot_id in late] if since is not None else None
            return pages.metrics(results, gold, yield_pages=sub)

        return m(old), m(new)

    async def degraded(self, c: Change) -> bool:
        """The object's running version is degraded (a repair: the KPI is the new version's own accuracy); a site
        without a parser counts as degraded (nothing to compare with)."""
        if bool(c.evidence.get("degraded")):
            return True
        if c.object_kind != "parser" or not c.from_version:
            return c.object_kind == "parser"
        async with sessionmaker()() as s:
            old = await s.get(ParserVersion, c.from_version)
        return old is not None and old.status == "degraded"


def rule_sets(c: Change) -> tuple[dict[str, Any], dict[str, Any]]:
    """(rules before, after) of a plausibility or sense rule change, as `{"plausibility": …, "sense": …}`; a live
    change (watch, kept) has its old value as "before". Raises `NoMeasure` for other rules."""
    section = c.object_key.split(".", 1)[0]
    if section not in ("plausibility", "sense"):
        raise NoMeasure(f"no offline measure for {c.object_key}")
    path = c.object_key.removeprefix(section + ".")
    current = {"plausibility": acq_config.plausibility_rules(),
               "sense": overrides.layer("sense", config.load_yaml("sense.yaml"))}  # fmt: skip
    before = c.diff.get("from")
    after = {**current, section: overrides.set_path(current[section], path, c.diff.get("to"))}
    if c.status in ("watch", "kept") and before is not None:
        current = {**current, section: overrides.set_path(current[section], path, before)}
    return current, after


async def _parser_pair(c: Change, refs: list[SnapshotRef]) -> Pair:
    old, new = await pages.spec_of(c.from_version), await pages.spec_of(c.to_version)
    bodies, variants = await pages.bodies_and_variants(refs)
    rules = acq_config.plausibility_rules()
    return pages.read(refs, bodies, variants, old, rules), pages.read(refs, bodies, variants, new, rules)


async def _rule_pair(c: Change, refs: list[SnapshotRef]) -> Pair:
    before, after = rule_sets(c)
    specs = await pages.running_specs()
    bodies, variants = await pages.bodies_and_variants(refs)
    old: list[scoring.PageResult] = []
    new: list[scoring.PageResult] = []
    for r in refs:
        sp = pages.spec_for(specs, r.domain)
        if sp is None:
            continue
        with _sense(before["sense"]):
            old += pages.read([r], bodies, variants, sp, before["plausibility"])
        with _sense(after["sense"]):
            new += pages.read([r], bodies, variants, sp, after["plausibility"])
    return old, new


@contextmanager
def _sense(rules: dict[str, Any]) -> Iterator[None]:
    """The sense checks with these rules for the (synchronous) block."""
    saved = dict(sense.RULES)
    sense.configure(rules)
    try:
        yield
    finally:
        sense.configure(saved)
