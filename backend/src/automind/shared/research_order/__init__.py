"""Shared · automind.shared.research_order: what to research for which car, and the search queries for it. Pure.

Owns:
- `plan` — the case-driven research plan: needed areas, freshness, minimum evidence per area, gap rounds.
- `search_plan` — the search queries per round and market: favourite sites first, then open-web templates.
Flow: the chat decides the cars and areas (`plan`) → the engine turns each job into queries (`search_plan`).
Depends on: shared.evidence (deny list, domains). Must not depend on: chat, acquisition, observability, delivery,
shared.infrastructure (pure domain: import contract `domain-pure`).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["plan", "search_plan"]
