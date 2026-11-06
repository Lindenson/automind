"""Daily parser metrics and drift (spec 011 T089, research R11-R12): worker tasks `parser_daily` and `drift`.

`roll_day(day)` writes `parser_daily` for every parser version that read pages that day: the stored pages are read
again by that version's spec (fields per page, zero pages — deterministic, the same interpreter as live), the claims
the version produced give the check pass rate, and the pages' structure fingerprint gives the day's most frequent
hash, its shingles and its similarity to the 30-day reference (the most frequent hash of the 30 days before).
Missing earlier days of the 37-day window are rolled up first, oldest first, so a fresh database catches up.

`detect(day)` runs the pure detectors (`domain/drift.py`) on each running version; on drift an active version is
degraded, journalled in `acq_changes` and handed to the parser doctor (`parsing/store.degrade`). Both tasks publish
the parser gauges of the worker's exporter.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.domain import drift
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.parsing import fingerprint, interpreter
from automind.acquisition.parsing import store as parsers
from automind.acquisition.parsing.spec import ParserSpec
from automind.acquisition.snapshots import store as snapshots
from automind.shared.infrastructure.db import ParserDaily, sessionmaker

log = logging.getLogger(__name__)
WINDOW_DAYS = 37  # 7 recent days + the 30-day baseline before them (domain/drift.py)
REFERENCE_DAYS = 30


def _cfg() -> drift.DriftConfig:
    return drift.DriftConfig.from_mapping(acq_config.acquisition_config().get("drift"))


def _bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


async def _rows(sql: str, **params: Any) -> list[Any]:
    async with sessionmaker()() as s:
        return list((await s.execute(text(sql), params)).all())


async def _spec(key: str, cache: dict[str, ParserSpec | None]) -> ParserSpec | None:
    if key not in cache:
        try:
            v = await parsers.version(key)
        except ValueError:
            v = None
        cache[key] = v.spec if v is not None else None
    return cache[key]


async def _reference(key: str, day: date) -> list[str] | None:
    """Shingles of the most frequent structure hash (by pages) of the 30 days before `day`."""
    async with sessionmaker()() as s:
        rows = (
            await s.execute(
                select(ParserDaily.structure_hash, ParserDaily.structure_shingles, ParserDaily.pages).where(
                    ParserDaily.version_key == key,
                    ParserDaily.day >= day - timedelta(days=REFERENCE_DAYS),
                    ParserDaily.day < day,
                    ParserDaily.structure_hash.is_not(None),
                )
            )
        ).all()
    if not rows:
        return None
    weight: Counter[str] = Counter()
    shingles: dict[str, list[str]] = {}
    for h, sh, pages in rows:
        weight[h] += int(pages or 0)
        shingles.setdefault(h, list(sh or []))
    return shingles[weight.most_common(1)[0][0]]


async def roll_version_day(key: str, day: date, specs: dict[str, ParserSpec | None]) -> bool:
    """One `parser_daily` row; False when the version read no page that day."""
    start, end = _bounds(day)
    snaps = await _rows(
        "SELECT id, blob_sha256, structure_hash, coalesce(final_url, url) FROM page_snapshots "
        "WHERE parser_version = :k AND fetched_at >= :a AND fetched_at < :b",
        k=key, a=start, b=end,
    )  # fmt: skip
    if not snaps:
        return False
    spec = await _spec(key, specs)
    labels = fingerprint.spec_labels(spec) if spec is not None else None
    ids = [str(r[0]) for r in snaps]
    claims = {
        str(sid): (int(n), int(ok))
        for sid, n, ok in await _rows(
            "SELECT snapshot_id, count(*), count(*) FILTER (WHERE status = 'ACCEPTED') FROM claims "
            "WHERE producer_version = :k AND snapshot_id = ANY(:ids) GROUP BY snapshot_id",
            k=key, ids=ids,
        )
    }  # fmt: skip
    bodies = await snapshots.load_bodies(sorted({str(r[1]) for r in snaps if r[1]}))
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415

    fields_total = zero = 0
    hashes: Counter[str] = Counter()
    shingles: dict[str, frozenset[str]] = {}
    for sid, sha, stored_hash, url in snaps:
        raw = bodies.get(str(sha)) if sha else None
        if raw is not None and spec is not None:
            html = decode_body(raw, None)
            try:
                n = len(interpreter.read_rows(spec, html, url).rows)
                fp = fingerprint.structure(html, labels)
            except Exception:  # noqa: BLE001 - a broken page reads as nothing, as live
                n, fp = 0, None
            if fp is not None:
                hashes[fp.hash] += 1
                shingles.setdefault(fp.hash, fp.shingles)
        else:  # body gone (not replayable): the claims the version produced, the hash the reader stored
            n = claims.get(str(sid), (0, 0))[0]
            if stored_hash:
                hashes[str(stored_hash)] += 1
        fields_total += n
        zero += n == 0
    read = sum(n for n, _ in claims.values())
    accepted = sum(ok for _, ok in claims.values())
    top = hashes.most_common(1)[0][0] if hashes else None
    top_shingles = sorted(shingles[top]) if top in shingles else None
    sim = None
    if top_shingles is not None and (ref := await _reference(key, day)) is not None:
        sim = round(fingerprint.similarity(top_shingles, ref), 4)
    row = {
        "version_key": key, "day": day, "pages": len(snaps), "fields_total": fields_total,
        "fields_per_page": fields_total / len(snaps), "rows_read": read, "rows_accepted": accepted,
        "pass_rate": (accepted / read) if read else None, "zero_pages": zero, "structure_hash": top,
        "structure_shingles": top_shingles, "structure_sim": sim,
    }  # fmt: skip
    stmt = insert(ParserDaily).values(**row)
    async with sessionmaker()() as s:
        await s.execute(stmt.on_conflict_do_update(
            index_elements=["version_key", "day"],
            set_={k: stmt.excluded[k] for k in row if k not in ("version_key", "day")},
        ))  # fmt: skip
        await s.commit()
    return True


async def roll_day(day: date) -> dict[str, Any]:
    """`parser_daily` for `day` (always recomputed) and for the missing days of the window before it."""
    start, end = _bounds(day)
    first = start - timedelta(days=WINDOW_DAYS - 1)
    todo = await _rows(
        "SELECT DISTINCT s.parser_version, (s.fetched_at AT TIME ZONE 'UTC')::date AS d FROM page_snapshots s "
        "JOIN parser_versions v ON v.key = s.parser_version "
        "WHERE s.fetched_at >= :a AND s.fetched_at < :b "
        "AND ((s.fetched_at AT TIME ZONE 'UTC')::date = :day OR NOT EXISTS ("
        "  SELECT 1 FROM parser_daily p WHERE p.version_key = s.parser_version "
        "  AND p.day = (s.fetched_at AT TIME ZONE 'UTC')::date)) "
        "ORDER BY d",
        a=first, b=end, day=day,
    )  # fmt: skip
    specs: dict[str, ParserSpec | None] = {}
    rows = 0
    for key, d in todo:
        rows += await roll_version_day(str(key), d, specs)
    return {"day": day.isoformat(), "rows": rows, "versions": sorted({str(k) for k, _ in todo})}


async def _days(key: str, day: date) -> list[drift.DayStat]:
    async with sessionmaker()() as s:
        rows = (
            await s.execute(
                select(ParserDaily).where(
                    ParserDaily.version_key == key,
                    ParserDaily.day > day - timedelta(days=WINDOW_DAYS),
                    ParserDaily.day <= day,
                )
            )
        ).scalars()
        return [
            drift.DayStat(r.day, r.pages, r.fields_total, r.rows_read, r.rows_accepted, r.zero_pages, r.structure_sim)
            for r in rows
        ]


async def detect(day: date) -> dict[str, Any]:
    """Run the detectors on every running version; degrade the active ones that drifted."""
    cfg = _cfg()
    out: dict[str, Any] = {"day": day.isoformat(), "checked": 0, "degraded": {}}
    for v in await parsers.running():
        days = await _days(v.key, day)
        out["checked"] += 1
        verdict = drift.verdict(days, day, cfg)
        if verdict is None:
            continue
        log.info("parser.drift key=%s kind=%s reason=%s", v.key, verdict.kind, verdict.reason)
        if v.status == "active":
            w7, w30, _ = drift.windows(days, day)
            evidence = {"day": day.isoformat(), "window_7d": w7.__dict__, "baseline_30d": w30.__dict__}
            if await parsers.degrade(v.key, verdict, evidence=evidence):
                out["degraded"][v.key] = verdict.reason
    await publish_gauges(day)
    return out


async def publish_gauges(day: date | None = None) -> None:
    """automind_parser_fields_per_page / _pass_rate {reader, version} over the last 7 days, and
    automind_parser_drift {reader} (1 while the running version is degraded)."""
    from automind.acquisition.worker import exporter  # noqa: PLC0415

    day = day or datetime.now(UTC).date()
    fpp: dict[tuple[str, str], float] = {}
    rate: dict[tuple[str, str], float] = {}
    drifting: dict[str, float] = {}
    for v in await parsers.running():
        w7, _, _ = drift.windows(await _days(v.key, day), day)
        if w7.fields_per_page is not None:
            fpp[(v.spec.reader, v.key)] = w7.fields_per_page
        if w7.pass_rate is not None:
            rate[(v.spec.reader, v.key)] = w7.pass_rate
        drifting[v.spec.reader] = 1.0 if v.status == "degraded" else 0.0
    exporter.set_parsers(fpp, rate, drifting)
