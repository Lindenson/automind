"""Acquisition · acquisition.registry.infrastructure: registry persistence and the facts for admission.

Owns:
  `repo` — RegistryRepo: the registry tables.
  `terms` — facts for the admission check: robots, readable content, terms of use read by the `terms_reader` role.
Depends on: registry.api, registry.domain, acquisition.domain, infrastructure (config, fetch), reputation, snapshots,
  shared (infrastructure.db, config, llm, evidence), observability.metrics; pydantic, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["repo", "terms"]
