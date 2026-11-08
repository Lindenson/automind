"""Acquisition · acquisition.infrastructure.search: interchangeable providers behind a cache-first Searcher.

Owns:
  `cache` — CachedSearcher: search_cache (Postgres) → primary provider → fallback providers; usage recorded.
  `serper` — Serper (serper.dev); `serpapi` — SerpApi; `tavily` — Tavily, fallback / baseline only.
  This `__init__` — SearchUnavailable: the provider cannot answer (no key, no credit, rate limit, server error).
Flow: CachedSearcher.search → cache hit, else primary provider, else fallbacks; deny-listed URLs dropped first.
Depends on: chat.infrastructure.persistence (UsageRepo), shared (infrastructure, contracts, evidence, metering),
  observability.metrics; sqlalchemy, tavily.
Must not depend on: as acquisition/__init__ (registry-no-chat). Pure cores and the chat's application must not import
  this package (domain-pure, application-ports).
Public API: the names in __all__; the providers and the searcher are wired in infrastructure.wiring.
Note: search usage is recorded through the chat's UsageRepo (chat.infrastructure).
"""

from __future__ import annotations

from automind.shared.contracts.web import SearchUnavailable

__all__ = ["SearchUnavailable"]
