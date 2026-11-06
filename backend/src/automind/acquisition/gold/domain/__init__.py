"""Acquisition · acquisition.gold.domain: pure gold matching — dataset rows to gold values, no I/O.

Owns:
  `match` — open-dataset rows → gold values of one catalogue variant (DatasetRow, VariantKey, GoldValue).
  `versions` — distinct registered versions of a model from the dataset rows.
Depends on: nothing outside this package.
Must not depend on:
  I/O and frameworks (sqlalchemy, httpx, fastapi, langchain, langgraph, prometheus_client), shared.infrastructure,
  chat.application / dialog / infrastructure, infrastructure.search / retention / overrides
  (import-linter acquisition-domain-pure).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["match", "versions"]
