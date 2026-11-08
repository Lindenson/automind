"""Acquisition · acquisition.registry.infrastructure: the registry's stores, the facts for admission, and wiring.

Owns:
  `capability_store` — capabilities and the attempts on them; `signal_store` — truth signals applied by blame;
  `admission_store` — sites due for a check and their verdicts; `review_store` — the review's unit of work;
  `seed_store` — the registry's first content; `rows` — capability rows faded, rescored and read as records.
  `terms` — facts for the admission check: robots, readable content, terms of use read by the `terms_reader` role.
  `pages` — the stored pages an attempt read; `seed_config` — favourites, survey and deny-list as configured.
  `wiring` — the services built over these (callers use `wiring.x()`).
Errors: every store raises registry.application.ports.RegistryStoreUnavailable (shared.infrastructure.db.errors).
Depends on: registry.api, registry.application (ports, services), registry.domain, acquisition.domain,
  acquisition.infrastructure (config, fetch), reputation.infrastructure (components), snapshots, shared
  (infrastructure.db, config, llm, evidence, metrics); pydantic, sqlalchemy, yaml.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["admission_store", "capability_store", "pages", "review_store", "rows", "seed_config",
                      "seed_store", "signal_store", "terms", "wiring"]  # fmt: skip
