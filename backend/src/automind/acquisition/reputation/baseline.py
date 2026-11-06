"""KPI baseline before registry autonomy (spec 011 FR-014, T073, research R7).

A window (`kpi_baselines` row) records, while it is open, the accuracy KPI (share of accepted values with a wrong
signal, by area), the satisfaction index, the nodata share by area, web searches per accepted value by area and the
coverage. The daily `baseline` task refreshes the values of open windows; `close` refuses before 7 days. The owner
switches `registry.autonomy` on by hand after a closed baseline (T078): this module never reads or writes it.

    python -m automind.acquisition.reputation.baseline start|status|close --name pre-autonomy [--note "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from automind.acquisition.reputation.rollup import kpis
from automind.shared.infrastructure.db import KpiBaseline, sessionmaker

MIN_DAYS = 7


class BaselineError(RuntimeError):
    pass


async def _scalar_rows(sql: str, **params: Any) -> list[Any]:
    async with sessionmaker()() as s:
        return list((await s.execute(text(sql), params)).all())


async def compute(start: datetime, end: datetime) -> dict[str, Any]:
    """The baseline's values over [start, end]."""
    k = await kpis(start.date(), end.date())
    sat = await _scalar_rows(
        "SELECT avg(score), count(*) FROM turn_outcomes WHERE created_at >= :t0 AND created_at < :t1 "
        "AND status <> 'WAITING_CONFIRMATION'",
        t0=start,
        t1=end,
    )
    reports = await _scalar_rows(
        "SELECT signals FROM turn_outcomes WHERE created_at >= :t0 AND created_at < :t1 AND action = 'REPORT'",
        t0=start,
        t1=end,
    )
    per_area: dict[str, int] = defaultdict(int)
    with_gap = 0
    for (sig,) in reports:
        areas = {i.get("area") for i in (sig or {}).get("nodata_items") or [] if i.get("area")}
        with_gap += 1 if areas else 0
        for a in areas:
            per_area[a] += 1
    n = len(reports)
    return {
        "accuracy_share_wrong": k["wrong_share"],
        "searches_per_value": k["searches_per_value"],
        "satisfaction_index": float(sat[0][0]) if sat and sat[0][0] is not None else None,
        "turns": int(sat[0][1]) if sat else 0,
        "nodata_share": {a: c / n for a, c in sorted(per_area.items())} if n else {},
        "coverage": 1 - with_gap / n if n else None,
        "reports": n,
        "days": round((end - start).total_seconds() / 86400, 2),
    }


async def _open(s: Any, name: str) -> KpiBaseline | None:
    q = select(KpiBaseline).where(KpiBaseline.name == name, KpiBaseline.ended_at.is_(None))
    return (await s.execute(q.order_by(KpiBaseline.started_at.desc()).limit(1))).scalar_one_or_none()


async def start(name: str, note: str | None = None, at: datetime | None = None) -> str:
    async with sessionmaker()() as s:
        if await _open(s, name) is not None:
            raise BaselineError(f"baseline {name!r} is already open")
        row = KpiBaseline(name=name, started_at=at or datetime.now(UTC), values={}, note=note)
        s.add(row)
        await s.commit()
        return row.id


async def status(name: str) -> dict[str, Any] | None:
    async with sessionmaker()() as s:
        q = select(KpiBaseline).where(KpiBaseline.name == name).order_by(KpiBaseline.started_at.desc()).limit(1)
        row = (await s.execute(q)).scalar_one_or_none()
    if row is None:
        return None
    return {"id": row.id, "name": row.name, "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None, "values": row.values,
            "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None, "note": row.note}  # fmt: skip


async def close(name: str, now: datetime | None = None) -> dict[str, Any]:
    t = now or datetime.now(UTC)
    async with sessionmaker()() as s:
        row = await _open(s, name)
        if row is None:
            raise BaselineError(f"no open baseline {name!r}")
        if t - row.started_at < timedelta(days=MIN_DAYS):
            days = (t - row.started_at).total_seconds() / 86400
            raise BaselineError(f"baseline {name!r} has run {days:.1f} days; it needs at least {MIN_DAYS}")
        row.values, row.recorded_at, row.ended_at = await compute(row.started_at, t), t, t
        await s.commit()
        return dict(row.values)


async def record_open() -> dict[str, Any]:
    """The daily `baseline` task: refresh the values of every open window."""
    t = datetime.now(UTC)
    async with sessionmaker()() as s:
        rows = list((await s.execute(select(KpiBaseline).where(KpiBaseline.ended_at.is_(None)))).scalars())
        for row in rows:
            row.values, row.recorded_at = await compute(row.started_at, t), t
        await s.commit()
    return {"open": [r.name for r in rows]}


async def main_async(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="baseline", description="KPI baseline before registry autonomy")
    ap.add_argument("action", choices=("start", "status", "close"))
    ap.add_argument("--name", default="pre-autonomy")
    ap.add_argument("--note")
    args = ap.parse_args(argv)
    try:
        if args.action == "start":
            out: Any = {"started": await start(args.name, args.note)}
        elif args.action == "status":
            out = await status(args.name)
        else:
            out = {"closed": args.name, "values": await close(args.name)}
    except BaselineError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(sys.argv[1:])))
