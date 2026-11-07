"""Acquisition · acquisition.reputation.domain: pure rules of the reputation KPIs.

Owns: `baseline` — the values of a KPI baseline window and when a window may close.
Must not depend on: storage, the network, the application layer.
Public API: the modules in __all__.
"""

__all__ = ["baseline"]
