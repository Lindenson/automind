"""Acquisition · acquisition.reputation.infrastructure: the stores behind the reputation's ports, and their wiring.

Owns: `signal_facts_repo` (a version's facts), `page_texts` (stored pages' text), `component_store`
  (`component_reputation`; `add` runs in the registry's transaction), `rollup_store` (`acq_daily` and the day's
  counts, the worker's gauges), `baseline_store` (`kpi_baselines`, the roll-up's KPIs), `physics_points` (the
  envelope's points), `wiring` (`signal_scan()`, `daily_rollup()`; the baseline is wired in `delivery.baselines`).
Depends on: acquisition.reputation.application (the ports), gold, registry, snapshots, worker, shared.infrastructure.
Public API: the modules in __all__.
"""

__all__ = ["baseline_store", "component_store", "page_texts", "physics_points", "rollup_store", "signal_facts_repo",
           "wiring"]  # fmt: skip
