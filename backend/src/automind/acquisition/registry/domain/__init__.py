"""Acquisition · acquisition.registry.domain: the registry's pure rules and entities.

Owns:
  `model` — Source, Capability; `score` — quality of a source for a kind of data (yield, accuracy, Wilson bound).
  `lifecycle` — discovered → candidate → active → … transitions; `limits` — hard limits no change may cross.
  `admission` — the admission check of a new site; `families` — mirror families counted as one.
  `seed_rules` — how the registry starts; `blame` — who was wrong (kept for callers).
Depends on: acquisition.domain.
Must not depend on: registry.application, registry.infrastructure,
  I/O and frameworks (sqlalchemy, httpx, fastapi, langchain, langgraph, prometheus_client), shared.infrastructure,
  chat.application / dialog / infrastructure, infrastructure.search / retention / overrides
  (import-linter registry-domain-pure).
Public API: the modules in __all__ (callers import from them).
Note: `blame` is superseded by acquisition.domain.blame (vector blame) and kept only for its callers.
"""

__all__: list[str] = ["admission", "blame", "families", "lifecycle", "limits", "model", "score", "seed_rules"]
