"""Observability · automind.observability.infrastructure: storage of outcomes and issues, reading both journals.

Owns:
- `outcomes` — `OutcomeRepo`: turn outcomes (scored by domain.outcome) and the one feedback table; `settings_version`.
- `repo` — `failures` read from the journals of both cycles, `IssueRepo` for `insight_issues` and `insight_runs`.
Depends on: observability.domain, observability.metrics, shared.infrastructure.db.
Must not depend on: chat, acquisition, delivery (it reads their tables by SQL, listed in scripts/table_owners.yaml).
Note: chat.infrastructure.adapters still builds the `OutcomeRepo` (composition moves later, S10/S12).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["outcomes", "repo"]
