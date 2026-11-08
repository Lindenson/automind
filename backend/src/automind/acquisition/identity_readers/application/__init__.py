"""Acquisition · acquisition.identity_readers.application: the registered-versions reader behind its ports.

Owns:
  `ports` — VersionBook (stored and cached dataset groups), LiveRows (the live query); one
    `IdentityStoreUnavailable`.
  `dataset_versions` — DatasetVersions: stored gold first, then the cache, then one bounded live query (cached).
Flow: identity_readers.infrastructure.wiring builds the service; the rules are in identity_readers.domain.
Depends on: identity_readers.domain, gold.domain.
Must not depend on: identity_readers.infrastructure, gold.infrastructure, sqlalchemy, httpx, shared.infrastructure.
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["dataset_versions", "ports"]
