"""Acquisition · acquisition.gold.domain: pure gold rules — records, matching, choice; no I/O.

Owns:
  `records` — DatasetRow, CandidateVariant, VariantKey, GoldValue, StoredGold, DatasetInfo.
  `text` — normalised names, makes through aliases, fuels, tolerances, the weighted median.
  `config` — MatchCfg and GoldRules: config/gold_datasets.yaml typed once.
  `match` — open-dataset rows → gold values of one catalogue variant.
  `reference` — the reference set's entries → gold of the variants they name.
  `choice` — the best gold per attribute, gold contradicted by families, gold of a settled challenge.
Depends on: parsing.normalise (fuel), shared (contracts.json, vehicle.specs).
Must not depend on:
  I/O and frameworks (sqlalchemy, httpx, fastapi, langchain, langgraph, prometheus_client), shared.infrastructure,
  chat.application / dialog / infrastructure, infrastructure.search / retention / overrides
  (import-linter acquisition-domain-pure).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["choice", "config", "match", "records", "reference", "text"]
