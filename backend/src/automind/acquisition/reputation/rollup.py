"""Daily roll-up (spec 011 T072, research R7, SC-009): `acq_daily` per day, area and market.

- `searches`        Serper/Tavily searches: `search_calls` (not cached) under market `*` (they carry no market), plus
                    `registry_attempts.searches` per market when the pipeline fills it
- `pages`, `accepted_values`, `cost_eur`, `explore_eur`  from `registry_attempts` (explore: candidates' attempts)
- `wrong_values`, `gold_checked`, `gold_wrong`  from `truth_signals`

The daily run also resets today's exploration spend (`capabilities.explore_spent_eur`) and fades
`component_reputation`; it publishes the worker gauges `automind_searches_per_accepted_value{area}`,
`automind_wrong_share{area}` and `automind_component_acc_lb{kind}` (7-day windows).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.reputation import components
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import AcqDaily, CapabilityRow, sessionmaker

log = logging.getLogger(__name__)
ANY_MARKET = "*"

_ATTEMPTS = text(
    """
    SELECT c.area, c.market, count(*), coalesce(sum(CASE WHEN a.outcome = 'accepted' THEN a.values ELSE 0 END), 0),
           coalesce(sum(a.searches), 0), coalesce(sum(a.cost_eur), 0),
           coalesce(sum(CASE WHEN c.status = 'candidate' THEN a.cost_eur ELSE 0 END), 0)
    FROM registry_attempts a JOIN capabilities c ON c.id = a.capability_id
    WHERE a.created_at >= :t0 AND a.created_at < :t1 GROUP BY 1, 2
    """
)
_SEARCHES = text(
    """
    SELECT coalesce(area, 'unknown'), count(*), coalesce(sum(cost_eur), 0) FROM search_calls
    WHERE created_at >= :t0 AND created_at < :t1 AND kind = 'search' AND NOT cached GROUP BY 1
    """
)
_SIGNALS = text(
    """
    SELECT coalesce(t.details->>'area', 'unknown'), coalesce(c.market, :any),
           count(DISTINCT CASE WHEN t.verdict = 'wrong' THEN coalesce(t.claim_id, t.id) END),
           count(*) FILTER (WHERE t.kind = 'gold'), count(*) FILTER (WHERE t.kind = 'gold' AND t.verdict = 'wrong')
    FROM truth_signals t LEFT JOIN capabilities c ON c.id = t.capability_id
    WHERE t.created_at >= :t0 AND t.created_at < :t1 GROUP BY 1, 2
    """
)


def _bounds(day: date) -> dict[str, Any]:
    t0 = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return {"t0": t0, "t1": t0 + timedelta(days=1), "any": ANY_MARKET}


async def roll_day(day: date) -> int:
    """Recompute the `acq_daily` rows of one day (idempotent)."""
    rows: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    p = _bounds(day)
    async with sessionmaker()() as s:
        for area, market, pages, values, searches, cost, explore in (await s.execute(_ATTEMPTS, p)).all():
            r = rows[(area, market)]
            r["pages"] += pages
            r["accepted_values"] += values
            r["searches"] += searches
            r["cost_eur"] += float(cost)
            r["explore_eur"] += float(explore)
        for area, n, cost in (await s.execute(_SEARCHES, p)).all():
            r = rows[(area, ANY_MARKET)]
            r["searches"] += n
            r["cost_eur"] += float(cost)
        for area, market, wrong, checked, gold_wrong in (await s.execute(_SIGNALS, p)).all():
            r = rows[(area, market)]
            r["wrong_values"] += wrong
            r["gold_checked"] += checked
            r["gold_wrong"] += gold_wrong
        for (area, market), r in rows.items():
            vals: dict[str, Any] = {
                k: int(r.get(k, 0))
                for k in ("searches", "pages", "accepted_values", "wrong_values", "gold_checked", "gold_wrong")
            }
            vals["cost_eur"] = round(r.get("cost_eur", 0.0), 4)
            vals["explore_eur"] = round(r.get("explore_eur", 0.0), 4)
            stmt = insert(AcqDaily).values(day=day, area=area[:20], market=market[:8], **vals)
            await s.execute(stmt.on_conflict_do_update(index_elements=["day", "area", "market"], set_=vals))
        await s.commit()
    return len(rows)


async def kpis(since: date, until: date | None = None) -> dict[str, dict[str, float]]:
    """Searches per accepted value and wrong share by area over [since, until] from `acq_daily`."""
    q = text(
        "SELECT area, sum(searches), sum(accepted_values), sum(wrong_values) FROM acq_daily "
        "WHERE day >= :d0 AND day <= :d1 GROUP BY 1"
    )
    async with sessionmaker()() as s:
        rows = (await s.execute(q, {"d0": since, "d1": until or datetime.now(UTC).date()})).all()
    spv: dict[str, float] = {}
    wrong: dict[str, float] = {}
    for area, searches, accepted, wrong_n in rows:
        if accepted:
            spv[area] = float(searches) / float(accepted)
            wrong[area] = float(wrong_n) / float(accepted)
    return {"searches_per_value": spv, "wrong_share": wrong}


async def publish_gauges() -> dict[str, Any]:
    """The worker's reputation gauges over the last 7 days (and the closed baseline's wrong share)."""
    from automind.acquisition.worker import exporter  # noqa: PLC0415

    k = await kpis(datetime.now(UTC).date() - timedelta(days=6))
    comp = await components.acc_lb_by_kind()
    base: dict[str, float] = {}
    async with sessionmaker()() as s:
        row = (
            await s.execute(
                text('SELECT "values" FROM kpi_baselines WHERE ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1')
            )
        ).first()
    if row and isinstance(row[0], dict):
        base = {str(a): float(v) for a, v in (row[0].get("accuracy_share_wrong") or {}).items()}
    exporter.set_reputation(k["searches_per_value"], k["wrong_share"], comp, base)
    return {"areas": len(k["searches_per_value"]), "components": len(comp)}


async def run(day: date | None = None, reset: bool = True) -> dict[str, Any]:
    """The daily `rollup` task: yesterday and today so far, then the resets and the gauges."""
    today = datetime.now(UTC).date()
    days = [day] if day else [today - timedelta(days=1), today]
    rows = 0
    for d in days:
        rows += await roll_day(d)
    out: dict[str, Any] = {"days": [d.isoformat() for d in days], "rows": rows}
    if reset:
        async with sessionmaker()() as s:
            await s.execute(update(CapabilityRow).values(explore_spent_eur=0.0))
            await s.commit()
        hl = float(load_yaml("registry.yaml")["half_life_days"])
        out["components_faded"] = await components.decay_all(hl)
    try:
        out.update(await publish_gauges())
    except Exception:  # noqa: BLE001 - gauges are best effort
        log.exception("rollup.gauges_failed")
    return out
