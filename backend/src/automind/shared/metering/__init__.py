"""Shared · automind.shared.metering: counts and limits every model and search call of a turn or engine job.

Owns:
- `usage` — `TurnBudget` (calls, tokens, €, per-turn limits; installed in a context variable), `Prices`, `Limits`,
  `BudgetExceeded`.
Flow: the chat runner or the engine job installs a budget → the LLM gateway and search adapters charge it → a limit
raises `BudgetExceeded`.
Depends on: the standard library only. Must not depend on: chat, acquisition, observability, delivery,
shared.infrastructure (import contract `application-ports`).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["usage"]
