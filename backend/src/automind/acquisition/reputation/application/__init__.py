"""Acquisition · acquisition.reputation.application: the reputation's services and their ports.

Owns: `signals` — `SignalScan`; `rollup` — `DailyRollup`; `baseline` — `KpiBaselines`; `errors` —
  `ReputationStoreUnavailable`, raised by every store behind these ports.
Depends on: acquisition.reputation.domain, acquisition.registry.api, shared.contracts.
Must not depend on: sqlalchemy, shared.infrastructure, any infrastructure package (the stores are ports).
Public API: the modules in __all__.
"""

__all__ = ["baseline", "errors", "rollup", "signals"]
