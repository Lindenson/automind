"""Acquisition · acquisition.identity_readers.infrastructure: the version store and wiring.

Owns:
  `version_store` — VersionStore: EEA group keys stored with gold (gold_values ⋈ vehicle_variants), the make's
    dataset rows cached in search_cache (provider `dataset`).
  `wiring` — `dataset_versions(ports)`, `live_rows(make)` (the engine's `AcqPorts.datasets`), `source_url()`.
Errors: the store raises identity_readers.application.ports.IdentityStoreUnavailable.
Depends on: identity_readers (application, domain), gold (domain, loaders, wiring), acquisition.ports, shared
  (contracts, infrastructure.db); sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["version_store", "wiring"]
