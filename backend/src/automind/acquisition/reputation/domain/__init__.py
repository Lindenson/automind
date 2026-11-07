"""Acquisition · acquisition.reputation.domain: pure rules of the reputation.

Owns: `signal_facts` — a version's stored facts and the `Finding`s; `findings` — the signal rules (gold, fusion,
  physics, agreement, replacement) and a wrong claim's blame; `components` — fading weights of the components;
  `rollup` — the daily rows and the KPIs; `baseline` — the values of a KPI baseline window.
Must not depend on: storage, the network, the application layer.
Public API: the modules in __all__.
"""

__all__ = ["baseline", "components", "findings", "rollup", "signal_facts"]
