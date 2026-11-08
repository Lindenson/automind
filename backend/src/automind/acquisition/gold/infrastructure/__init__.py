"""Acquisition · acquisition.gold.infrastructure: gold's stores, the open-data loaders and wiring.

Owns:
  `gold_store` — GoldStore: gold_datasets and gold_values (the GoldBook).
  `candidate_store` — CandidateStore: the catalogue variants gold is loaded for.
  `loaders` — EEA CO2, EEA OBFCM, RDW (official open-data APIs), the reference file, `ApiDataset`.
  `wiring` — the services built over these, the typed config (callers use `wiring.x()`).
Errors: the stores raise gold.application.ports.GoldStoreUnavailable (shared.infrastructure.db.errors); the loaders'
  errors are listed in gold.application.ports.
Depends on: gold.application (ports, services), gold.domain, infrastructure.config, shared (contracts,
  infrastructure.db, config); httpx, sqlalchemy, yaml.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["candidate_store", "gold_store", "loaders", "wiring"]
