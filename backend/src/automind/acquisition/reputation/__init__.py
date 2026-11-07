"""Acquisition · acquisition.reputation: honest accuracy signals, the reputation of the pipeline's components, the
daily roll-up and its KPIs, and the KPI baseline before registry autonomy.

Owns:
  `domain` — pure rules: the signal rules (`findings`) over a version's facts (`signal_facts`), the components'
    fading weights (`components`), the roll-up's rows and KPIs (`rollup`), the baseline's values (`baseline`).
  `application` — `SignalScan` (signals of the versions research touched), `DailyRollup` (rows, resets, gauges),
    `KpiBaselines` (windows); their ports and `ReputationStoreUnavailable`.
  `infrastructure` — the stores over the database, stored page texts, the physics points, and `wiring`.
Flow: worker `reputation_signals` → `SignalScan.scan` → registry truth signals (+ component shares) → `rollup` →
  `DailyRollup.run` → `acq_daily`, gauges; the owner closes a baseline (`automind.cli baseline`).
Depends on: acquisition.domain, gold, registry, snapshots, worker (queue, gauges), shared.
Must not depend on: as acquisition/__init__ (registry-no-chat); the outcomes of turns are read by observability and
  wired in delivery.
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["application", "domain", "infrastructure"]
