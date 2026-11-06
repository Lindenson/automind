"""Shared · automind.shared.infrastructure.llm: the LLM gateway, the single place that creates chat models.

Owns:
- `gateway` — model per role from config/models.yaml ("provider:model"), fallbacks and quota handling, budgets
  (`new_budget`), `chat_model`, `structured` and `text` calls (constitution VII).
- `usage_callback` — `UsageCallbackHandler`: attached to every model; checks limits before a call, records tokens,
  € and an `llm_calls` row after it.
Flow: caller asks for a role → `gateway` picks provider and model, attaches the callback → the call is charged to
the current `TurnBudget` (shared.metering) and recorded.
Depends on: shared.infrastructure.config, shared.metering, LangChain. Must not depend on: chat, acquisition,
delivery (target `shared-is-kernel`); observability.
Note: still imports acquisition.domain.served, acquisition.infrastructure.overrides, the chat UsageRepo and
observability.metrics.prom (kernel debt, untangled in later steps).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["gateway", "usage_callback"]
