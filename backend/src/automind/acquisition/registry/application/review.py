"""The registry's daily review (spec 010 US7, T066): fade, rescore, move statuses, journal every change.

Only with `registry.autonomy: true`. Every change passes the hard limits (domain/limits.py); a frozen source gets a
"held" journal entry instead of a change. Discovery and admission of new sites are separate steps (discovery.py).

    python -m automind.acquisition.registry.application.review --once
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from automind.acquisition.registry.application.admission import admit_pending
from automind.acquisition.registry.domain import limits
from automind.acquisition.registry.domain.lifecycle import CapState, transition
from automind.acquisition.registry.infrastructure.repo import RegistryRepo, _decay, _refresh
from automind.infrastructure.config import load_yaml
from automind.infrastructure.db.models import CapabilityRow, RegistryChange, RegistryRun, SourceRow, now
from automind.infrastructure.db.session import sessionmaker
from automind.insight.metrics import heartbeat, prom

log = logging.getLogger(__name__)
WAKE_S = 600
TOP_RANKS = 10  # re-ordering is journalled for the first ranks of each kind of data


def _ranks(caps: list[CapabilityRow]) -> dict[str, int]:
    by_area: dict[str, list[CapabilityRow]] = defaultdict(list)
    for c in caps:
        if c.status in ("active", "candidate", "degraded"):
            by_area[f"{c.area}|{c.market}"].append(c)
    out: dict[str, int] = {}
    for rows in by_area.values():
        rows.sort(key=lambda r: (r.status != "active", -r.score))
        for i, r in enumerate(rows):
            out[r.id] = i + 1
    return out


async def _reverts(s: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ch in (await s.execute(select(RegistryChange).where(RegistryChange.change == "reverted"))).scalars():
        if ch.capability_id and (ch.capability_id not in out or ch.created_at > out[ch.capability_id]):
            out[ch.capability_id] = ch.created_at
    return out


def _journal_reorders(s: Any, caps: list[CapabilityRow], before: dict[str, int], stats: dict[str, int]) -> None:
    after = _ranks(caps)
    for c in caps:
        b, a = before.get(c.id), after.get(c.id)
        if b and a and b != a and min(a, b) <= TOP_RANKS and abs(a - b) >= 2:
            s.add(
                RegistryChange(
                    author="system",
                    capability_id=c.id,
                    domain=c.domain,
                    change="reordered",
                    before={"rank": b},
                    after={"rank": a},
                    reason=f"{c.area}/{c.market}: moved from #{b} to #{a} by score {c.score:.3f}",
                    evidence={"score": c.score, "acc_lb": c.acc_lb, "yield": c.yield_},
                )
            )
            stats["reordered"] += 1
            prom.inc("registry_changes", change="reordered", author="system")


async def review(cfg: dict[str, Any] | None = None, kind: str = "daily", admit_sites: bool = True) -> dict[str, int]:
    cfg = cfg or load_yaml("registry.yaml")
    stats = {"changes": 0, "held": 0, "refused": 0, "reordered": 0}
    if not cfg.get("autonomy"):
        return stats
    deny = tuple(str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or [])
    if admit_sites:  # sites met in searches get their admission check first (FR-019)
        stats.update({f"admission_{k}": v for k, v in (await admit_pending(cfg)).items()})
    repo = RegistryRepo(cfg)
    t = now()
    async with sessionmaker()() as s:
        run = RegistryRun(kind=kind)
        s.add(run)
        caps = list((await s.execute(select(CapabilityRow))).scalars())
        sources = {r.domain: r for r in (await s.execute(select(SourceRow))).scalars()}
        reverts = await _reverts(s)
        before = _ranks(caps)
        for c in caps:
            src = sources.get(c.domain)
            _decay(c, repo.hl)
            _refresh(c, src.source_type if src else "OTHER", cfg)
            mv = transition(
                CapState(
                    c.status,
                    c.attempts,
                    c.acc_lb,
                    c.yield_,
                    c.status_since,
                    src.access if src else "unknown",
                    tuple(c.recent or []),
                ),
                cfg,
                t,
            )
            if mv is None or mv.to == c.status:
                continue
            rev = reverts.get(c.id)
            guard = limits.Guard(
                c.domain,
                src.access if src else "unknown",
                bool(src and src.frozen),
                c.status,
                rev,
                rev is None or (c.last_used is not None and c.last_used > rev),
            )
            verdict = limits.check(guard, mv.to, deny)
            if verdict == "refused":
                stats["refused"] += 1
                continue
            change = {
                "active": "promoted",
                "degraded": "demoted",
                "retired": "retired",
                "blocked": "blocked",
                "candidate": "promoted" if c.status == "discovered" else "reordered",
            }.get(mv.to, "reordered")
            s.add(
                RegistryChange(
                    author="system",
                    capability_id=c.id,
                    domain=c.domain,
                    change=change,
                    before={"status": c.status},
                    after={"status": mv.to},
                    reason=mv.reason,
                    evidence={
                        "acc_lb": c.acc_lb,
                        "yield": c.yield_,
                        "attempts": round(c.attempts, 2),
                        "area": c.area,
                        "market": c.market,
                    },
                    held=verdict == "held",
                )
            )
            if verdict == "held":
                stats["held"] += 1
                continue
            c.status, c.status_since = mv.to, t
            stats["changes"] += 1
            prom.inc("registry_changes", change=change, author="system")
        _journal_reorders(s, caps, before, stats)
        run.changes, run.finished_at = stats["changes"] + stats["reordered"], now()
        await s.commit()
    return stats


async def registry_loop() -> None:
    heartbeat.register("registry", WAKE_S)
    last_day = None
    while True:
        try:
            cfg = load_yaml("registry.yaml")
            today = now().date()
            if cfg.get("autonomy") and last_day != today:
                log.info("registry.review %s", await review(cfg))
                last_day = today
            heartbeat.beat("registry", True)
        except Exception:  # noqa: BLE001 - the loop must never stop the service
            log.exception("registry.review_failed")
            heartbeat.beat("registry", False)
        await asyncio.sleep(WAKE_S)


if __name__ == "__main__":
    if "--once" in sys.argv:
        print(asyncio.run(review(kind="manual")))
    else:
        print(__doc__)
