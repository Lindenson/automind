"""Chat · chat.infrastructure: the real implementations behind the chat's ports — database, events, checkpoints.

Owns: `persistence` — repositories for the conversation tables; `adapters` — `live_ports` (LLM, clock, estimator
  …) wired for the composition root; `events` — `EventBus`: persisted turn events fanned out to WebSockets;
  `checkpoint` — the LangGraph Postgres checkpointer; `models_on_sale` — models on sale known without a search.
Depends on: chat.application.ports, chat.domain, shared.infrastructure, sqlalchemy, langgraph, psycopg,
  acquisition (wiring, engine, registry), observability. Must not depend on: chat.dialog, delivery.web.
Note: acquisition, observability and shared import `adapters.LiveLLM` and repositories from here (shared plumbing).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["adapters", "checkpoint", "events", "models_on_sale", "persistence"]
