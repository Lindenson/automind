"""Registry use cases behind the port (spec 010 US6-US8). Never raises into research."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

from automind.acquisition.domain import thompson
from automind.acquisition.registry.api import Attempt, Plan, PlannedSource, TruthSignalIn
from automind.acquisition.registry.domain.model import ACCESS_BLOCKING

log = logging.getLogger(__name__)


class Store(Protocol):
    async def capabilities(self, area: str, markets: list[str]) -> list[dict[str, Any]]: ...
    async def record(self, attempts: list[Attempt]) -> None: ...
    async def queryable(self, area: str, markets: list[str]) -> list[dict[str, Any]]: ...
    async def signal(self, s: TruthSignalIn, weight: float) -> None: ...


_DOMAIN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[\w./-]*)?$")


def rank_queryable(rows: list[dict[str, Any]], markets: list[str], limit: int) -> list[PlannedSource]:
    """Pure order of the sources for `site:` queries: active (by score) before candidates (by seed priority, then
    score); within a status the markets keep the caller's order. One entry per domain."""
    order = {m: i for i, m in enumerate(markets)}
    usable = [
        r
        for r in rows
        if _DOMAIN.match(str(r["domain"]))
        and r.get("access") not in ACCESS_BLOCKING
        and (r["status"] == "active" or (r["status"] == "candidate" and r.get("access", "ok") == "ok"))
    ]
    usable.sort(key=lambda r: (r["status"] != "active", order.get(r["market"], len(order)),
                               -float(r.get("score") or 0.0), r.get("priority_seed") or 9, r["domain"]))  # fmt: skip
    out: list[PlannedSource] = []
    for r in usable:
        if len(out) >= limit:
            break
        if any(p.domain == r["domain"] for p in out):
            continue
        out.append(PlannedSource(domain=r["domain"], market=r["market"], priority=len(out), status=r["status"],
                                 unverified=r["status"] == "candidate"))  # fmt: skip
    return out


class RegistryService:
    def __init__(self, store: Store, cfg: Mapping[str, Any]) -> None:
        self.store = store
        self.cfg = cfg

    @property
    def autonomy(self) -> bool:
        return bool(self.cfg.get("autonomy", False))

    async def plan(self, area: str, markets: list[str], make: str | None, seed: int | None = None) -> Plan:
        """Ordered sources for an area. With autonomy off research keeps its configured order (the plan is empty
        apart from the skip list), so storage changes nothing (US8). With autonomy on, active sources are ordered by
        score and the candidates that get an exploration slot are drawn by Thompson sampling (spec 011 R7) while
        today's `explore.eur_per_day` lasts; `seed` (from the job id) makes the draw reproducible."""
        try:
            rows = await self.store.capabilities(area, [*markets, "ANY"])
        except Exception:  # noqa: BLE001 - research works without the registry
            log.exception("registry.plan_failed area=%s", area)
            return Plan(area=area)
        skip = sorted({r["domain"] for r in rows if r["status"] == "blocked"})
        if not self.autonomy:
            return Plan(area=area, autonomy=False, skip=skip)
        usable = [r for r in rows if r["status"] in ("active", "degraded")]
        usable.sort(
            key=lambda r: (r["status"] != "active", -float(r["score"]), r.get("priority_seed") or 9, r["domain"])
        )
        out: list[PlannedSource] = []
        seen: set[str] = set()
        for r in usable:
            if r["domain"] in seen:
                continue
            seen.add(r["domain"])
            out.append(PlannedSource(domain=r["domain"], market=r["market"], priority=len(out), status="active"))
        for r in await self._explore(area, markets, rows, seen, seed):
            seen.add(r["domain"])
            out.append(PlannedSource(domain=r["domain"], market=r["market"], priority=len(out), status="candidate",
                                     unverified=True))  # fmt: skip
        return Plan(area=area, autonomy=True, sources=out, skip=skip)

    async def _explore(
        self, area: str, markets: list[str], rows: list[dict[str, Any]], seen: set[str], seed: int | None
    ) -> list[dict[str, Any]]:
        explore_cfg = self.cfg.get("explore") or {}
        slots = min(int(self.cfg.get("candidate_slots", 1)), int(explore_cfg.get("max_candidates_per_job", 1)))
        try:
            spent = float(await self.store.explore_spent()) if hasattr(self.store, "explore_spent") else 0.0
        except Exception:  # noqa: BLE001
            log.exception("registry.explore_spent_failed")
            return []
        budget = float(explore_cfg.get("eur_per_day", 0.10)) - spent
        priors = self.cfg.get("priors") or {}
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        arms: list[thompson.Arm] = []
        for r in rows:
            if r["status"] != "candidate" or r["domain"] in seen:
                continue
            pr, pw = priors.get(r.get("source_type") or "OTHER") or priors.get("OTHER") or [1.0, 1.0]
            attempts = float(r.get("attempts") or 0.0)
            arms.append(thompson.Arm(
                domain=r["domain"], status=r["status"], right_w=float(r.get("right_w") or 0.0),
                wrong_w=float(r.get("wrong_w") or 0.0), prior_r=float(pr), prior_w=float(pw),
                accepted=float(r.get("accepted") or 0.0), attempts=attempts,
                cost_per_attempt=float(r.get("cost_eur") or 0.0) / attempts if attempts > 0 else 0.0,
                access=str(r.get("access") or "ok"), market=r["market"],
            ))  # fmt: skip
            by_key[(r["domain"], r["market"])] = r
        if seed is None:
            seed = thompson.seed_of(area, *markets)
        picked: list[dict[str, Any]] = []
        for a in thompson.explore(arms, seed, slots + 4, budget, float(self.cfg.get("cost_lambda", 2.0))):
            if len(picked) >= slots:
                break
            if any(p["domain"] == a.domain for p in picked):
                continue
            picked.append(by_key[(a.domain, a.market)])
        return picked

    async def sources_for(self, area: str, markets: list[str], limit: int) -> list[PlannedSource]:
        """Active sources first (best score first), then candidates the survey found open (robots and terms);
        never blocked, retired, degraded or merely discovered ones. Allowed with autonomy off: a query is an
        attempt, never a status change (spec 010 US8)."""
        if limit <= 0:
            return []
        try:
            rows = await self.store.queryable(area, markets)
        except Exception:  # noqa: BLE001 - research works without the registry
            log.exception("registry.sources_failed area=%s", area)
            return []
        return rank_queryable(rows, markets, limit)

    async def record(self, attempts: list[Attempt]) -> None:
        if not attempts:
            return
        try:
            await self.store.record(attempts)
        except Exception:  # noqa: BLE001 - never fail a job over the registry
            log.exception("registry.record_failed")

    async def signal(self, s: TruthSignalIn) -> None:
        try:
            weight = float((self.cfg.get("weights") or {}).get(s.kind, 1.0))
            await self.store.signal(s, weight)
        except Exception:  # noqa: BLE001
            log.exception("registry.signal_failed")
