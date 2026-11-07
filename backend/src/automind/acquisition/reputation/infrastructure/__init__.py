"""Acquisition · acquisition.reputation.infrastructure: the stores behind the reputation ports.

Owns: `baseline_store` — `BaselineRepo` (`kpi_baselines`), `RollupKpis` (`acq_daily` through `reputation.rollup`),
  `SystemClock`; the service is wired in `delivery.baselines` (the outcomes are observability's).
Depends on: acquisition.reputation.application (the ports), shared.infrastructure.db, sqlalchemy.
Public API: the modules in __all__.
"""

__all__ = ["baseline_store"]
