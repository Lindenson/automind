"""The reputation services wired over the database, the registry, the worker's queue and gauges, and the config
(`registry.yaml` families and half-life, `physics.yaml` checks). The KPI baseline is wired in `delivery.baselines`
(it reads observability's outcomes)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.acquisition.gold import repo as gold_repo
from automind.acquisition.infrastructure.config import physics_config
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.acquisition.reputation.application.rollup import DailyRollup
from automind.acquisition.reputation.application.signals import SignalScan, SignalSink
from automind.acquisition.reputation.domain.signal_facts import Tolerance
from automind.acquisition.reputation.infrastructure.baseline_store import BaselineRepo, SystemClock
from automind.acquisition.reputation.infrastructure.component_store import ComponentRepo
from automind.acquisition.reputation.infrastructure.page_texts import SnapshotPages
from automind.acquisition.reputation.infrastructure.rollup_store import RollupRepo, SystemToday, WorkerGauges
from automind.acquisition.reputation.infrastructure.signal_facts_repo import SignalFactsRepo
from automind.acquisition.worker import queue
from automind.shared.infrastructure.config.loader import load_yaml

JUDGE_PRIORITY = 7


def signal_scan(cfg: Mapping[str, Any] | None = None, sink: SignalSink | None = None) -> SignalScan:
    """The signal scan; `cfg` is `registry.yaml` (loaded when None), `sink` the registry (built from it when None)."""
    cfg = cfg if cfg is not None else load_yaml("registry.yaml")
    registry = sink if sink is not None else RegistryService(RegistryRepo(cfg), cfg)
    return SignalScan(SignalFactsRepo(cfg.get("families") or {}), SnapshotPages(), GoldTolerances(), registry,
                      QueueJudges(), SystemClock(), physics_config().get("checks") or {})  # fmt: skip


def daily_rollup() -> DailyRollup:
    """The daily roll-up with the components' half-life of `registry.yaml`."""
    half_life = float(load_yaml("registry.yaml")["half_life_days"])
    return DailyRollup(RollupRepo(), ComponentRepo(), BaselineRepo(), WorkerGauges(), SystemToday(), half_life)


class GoldTolerances:
    """Tolerances of `config/gold_datasets.yaml`, else the attribute's own."""

    def of(self, attribute: str) -> Tolerance:
        """The attribute's tolerance."""
        return gold_repo.tolerance_of(attribute)


class QueueJudges:
    """`blame_judge` tasks on the worker's queue, one per signal (deduplicated)."""

    async def judge(self, signal_ids: list[str]) -> int:
        """Queue a task per disputed signal; returns how many were new."""
        n = 0
        for sid in signal_ids:
            if await queue.enqueue("blame_judge", {"signal_id": sid}, dedupe_key=f"blame:{sid}",
                                   priority=JUDGE_PRIORITY):  # fmt: skip
                n += 1
        return n
