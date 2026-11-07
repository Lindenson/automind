"""Acquisition · acquisition.gates.application: the journal and the three gates as services over ports.

Owns: `journal` — `ChangeJournal` (propose and every transition); `replay_gate` — `ReplayGate`; `shadow_gate` —
  `ShadowGate`; `watch` — `Watch`; `settle` — a final verdict applied; `ports` — the stores, the queue, the events;
  `measure_ports` — the measures on stored pages and the agents' budgets, `NoMeasure`.
Depends on: acquisition.gates.domain, acquisition.domain (gates, relevance_audit), agents.levers, shared.contracts.
Must not depend on: sqlalchemy, shared.infrastructure, any infrastructure package (the stores are ports).
Public API: the modules in __all__.
"""

__all__ = ["journal", "measure_ports", "ports", "replay_gate", "settle", "shadow_gate", "watch"]
