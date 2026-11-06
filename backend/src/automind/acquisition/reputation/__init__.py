"""Acquisition · acquisition.reputation: honest accuracy signals and the reputation of sources and components.

Owns:
  `signals` — accuracy signals without the user, read after the fact from stored research.
  `components` — reputation of the pipeline components vector blame names.
  `rollup` — the daily roll-up `acq_daily` per day, area and market, and its KPIs.
  `baseline` — the KPI baseline window before registry autonomy.
  `fit_physics` — fit the power-mass-acceleration envelope of config/physics.yaml.
Flow: worker → signals.scan → registry truth signals and components.add → rollup.
Depends on: domain, gold, registry, snapshots, infrastructure.config, worker, shared (infrastructure.db, config);
  sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["baseline", "components", "fit_physics", "rollup", "signals"]
