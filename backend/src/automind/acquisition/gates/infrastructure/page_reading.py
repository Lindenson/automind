"""Stored pages read the live way for the gates (spec 011 US5, research R4): one code path with live — readers are
the fixed interpreter offline (socket guard on), values pass the live checks (`replay/run.read_page`); and the
headline metrics of a set of read pages against gold."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from automind.acquisition.domain import gates
from automind.acquisition.domain import replay as scoring
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.parsing import store as parsers
from automind.acquisition.parsing.spec import ParserSpec
from automind.acquisition.replay import run as replay
from automind.acquisition.replay.offline import no_network
from automind.acquisition.snapshots import store as snapshots
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.infrastructure.db.models import PageSnapshot, ParserVersion, Variant
from automind.shared.infrastructure.db.session import sessionmaker

Bodies = dict[str, bytes]
Variants = dict[str, Variant]


async def refs(ids: list[str]) -> list[SnapshotRef]:
    """The stored pages with these ids that have a body, oldest first."""
    if not ids:
        return []
    async with sessionmaker()() as s:
        q = select(PageSnapshot).where(PageSnapshot.id.in_(ids), PageSnapshot.blob_sha256.is_not(None))
        rows = (await s.execute(q)).scalars()
        out = [SnapshotRef(r.id, r.url, r.final_url, r.domain, r.fetched_at, r.content_type,
                           tuple(r.variant_ids or ()), str(r.blob_sha256)) for r in rows]  # fmt: skip
    return sorted(out, key=lambda r: (r.fetched_at, r.id))


async def corpus_refs(domains: list[str] | None, since: datetime, until: datetime,
                      limit: int = 5000) -> list[SnapshotRef]:  # fmt: skip
    """The replayable pages of these domains (all when None) fetched in [since, until), at most `limit`."""
    out: list[SnapshotRef] = []
    async for batch in snapshots.iter_replayable(domains, since, until):
        out += batch
        if len(out) >= limit:
            return out[:limit]
    return out


async def spec_of(key: str | None) -> ParserSpec | None:
    """A parser version's spec, None when there is none."""
    if not key:
        return None
    async with sessionmaker()() as s:
        row = await s.get(ParserVersion, key)
    return ParserSpec.model_validate(row.spec) if row is not None else None


async def running_specs() -> list[ParserSpec]:
    """The specs of the readers running now."""
    return [v.spec for v in await parsers.running()]


def spec_for(specs: list[ParserSpec], domain: str) -> ParserSpec | None:
    """The running reader of a page's site."""
    return next((sp for sp in specs if any(domain == d or domain.endswith("." + d) for d in sp.domains)), None)


async def bodies_and_variants(rs: list[SnapshotRef]) -> tuple[Bodies, Variants]:
    """The pages' stored bodies (by sha) and the catalogue versions they are about."""
    bodies = await snapshots.load_bodies(sorted({r.blob_sha256 for r in rs}))
    variants: Variants = {}
    await replay.load_variants({v for r in rs for v in r.variant_ids}, variants)
    return bodies, variants


def read(rs: list[SnapshotRef], bodies: Bodies, variants: Variants, spec: ParserSpec | None,
         rules: dict[str, Any]) -> list[scoring.PageResult]:  # fmt: skip
    """The pages read with `spec` offline (no spec: nothing read)."""
    out = []
    with no_network():
        for r in rs:
            if r.blob_sha256 not in bodies:
                continue
            if spec is None:
                out.append(scoring.PageResult(r.id, r.final_url or r.url, r.variant_ids, 0, []))
            else:
                out.append(replay.read_page(r, bodies[r.blob_sha256], spec, variants, rules))
    return out


async def gold_for(pages: list[scoring.PageResult]) -> dict[tuple[str, str], scoring.Gold]:
    """The gold values of the pages' versions."""
    return await replay.gold_values({v for p in pages for v in p.variant_ids})


def metrics(pages: list[scoring.PageResult], gold: dict[tuple[str, str], scoring.Gold], *,
            yield_pages: list[scoring.PageResult] | None = None) -> gates.Metrics:  # fmt: skip
    """Headline metrics; yield and pass rate from `yield_pages` when given (pages after a redesign), accuracy from
    every gold-covered page."""
    rep = scoring.report("x", pages, gold, acq_config.gold_tolerances())
    if yield_pages is not None:
        y = scoring.report("x", yield_pages, gold, acq_config.gold_tolerances())
        rep.update({k: y[k] for k in ("pages", "yield", "pass_rate", "rows_read", "rows_accepted")})
    found: dict[str, set[str]] = {}
    for p in yield_pages if yield_pages is not None else pages:
        for v in p.values:
            found.setdefault(v.variant_id, set()).add(v.attribute)
    rep["coverage"] = (sum(len(a) for a in found.values()) / len(found)) if found else None
    return gates.Metrics.from_report(rep)
