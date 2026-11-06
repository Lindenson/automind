"""Chat · chat.domain.case: the case file — the structured, versioned understanding of the person and the task.

Owns: `casefile` — `CaseFile` (profile, budget, needs, cars, intake, pending questions) and `CaseDelta`;
  `apply(case, delta)` is the only way the hub changes a case: pure, returns a new case plus a change log.
Flow: the LLM proposes a typed `CaseDelta` (application.services.interpretation) → `apply` validates and applies it
  → the latest explicit statement wins.
Depends on: pydantic. Must not depend on: sqlalchemy, langgraph, fastapi, chat.application, chat.dialog.
Note: `casefile.py` (804 lines) holds every case sub-model; split into a package by concept in S5.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["casefile"]
