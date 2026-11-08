"""Acquisition · acquisition.identity_readers: what identifies a car before research — web readers and registered
versions from the open datasets.

Owns:
  `web` — lineup, versions, generation_hints: searches, pages and the `lineup` / `versions` model roles.
  `domain` — `registered`: dataset groups → the distinct engines a model was registered with (pure).
  `application` — DatasetVersions (stored gold, then the cache, then one live query; never raises); its ports.
  `infrastructure` — VersionStore (gold_values keys, search_cache), wiring (`dataset_versions(ports)`, `live_rows`,
    `source_url`).
Flow: acquisition.backend (the api's `lineup`, `versions`, `generation_hints`, `dataset_versions`) → these.
Depends on: acquisition.api (contracts), acquisition.ports, gold (domain, loaders, wiring), shared (evidence,
  metering, vehicle, contracts, infrastructure.db).
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules and packages in __all__ (callers import from them).
"""

__all__: list[str] = ["application", "domain", "infrastructure", "web"]
