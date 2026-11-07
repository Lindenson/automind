"""Acquisition · acquisition.reputation.application: use cases over the reputation KPIs.

Owns: `baseline` — `KpiBaselines` (start, status, close, record the open windows) and its ports
  (`BaselineStore`, `OutcomeFacts`, `KpiSource`, `Clock`) with their errors.
Depends on: acquisition.reputation.domain, shared.contracts.
Must not depend on: sqlalchemy, shared.infrastructure, any infrastructure package (the stores are ports).
Public API: the modules in __all__.
"""

__all__ = ["baseline"]
