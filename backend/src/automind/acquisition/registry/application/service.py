"""Registry use cases behind the port (spec 010 US6-US8). Never raises into research."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from automind.acquisition.registry.api import Attempt, Plan, PlannedSource, TruthSignalIn

log = logging.getLogger(__name__)


class Store(Protocol):
    async def capabilities(self, area: str, markets: list[str]) -> list[dict[str, Any]]: ...
    async def record(self, attempts: list[Attempt]) -> None: ...
    async def signal(self, s: TruthSignalIn, weight: float) -> None: ...


class RegistryService:
    def __init__(self, store: Store, cfg: Mapping[str, Any]) -> None:
        self.store = store
        self.cfg = cfg

    @property
    def autonomy(self) -> bool:
        return bool(self.cfg.get("autonomy", False))

    async def plan(self, area: str, markets: list[str], make: str | None) -> Plan:
        """Ordered sources for an area. With autonomy off research keeps its configured order (the plan is empty
        apart from the skip list), so storage changes nothing (US8)."""
        try:
            rows = await self.store.capabilities(area, [*markets, "ANY"])
        except Exception:  # noqa: BLE001 - research works without the registry
            log.exception("registry.plan_failed area=%s", area)
            return Plan(area=area)
        skip = sorted({r["domain"] for r in rows if r["status"] == "blocked"})
        if not self.autonomy:
            return Plan(area=area, autonomy=False, skip=skip)
        usable = [r for r in rows if r["status"] in ("active", "candidate", "degraded")]
        usable.sort(key=lambda r: (r["status"] != "active", -float(r["score"]), r.get("priority_seed") or 9))
        slots = int(self.cfg.get("candidate_slots", 1))
        out: list[PlannedSource] = []
        seen: set[str] = set()
        for r in usable:
            if r["domain"] in seen:
                continue
            if r["status"] == "candidate":
                if slots <= 0:
                    continue
                slots -= 1
            seen.add(r["domain"])
            status = "active" if r["status"] in ("active", "degraded") else "candidate"
            out.append(
                PlannedSource(
                    domain=r["domain"],
                    market=r["market"],
                    priority=len(out),
                    status=status,
                    unverified=r["status"] == "candidate",
                )
            )
        return Plan(area=area, autonomy=True, sources=out, skip=skip)

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
