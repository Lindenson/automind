"""Acquisition · acquisition.snapshots: raw page bodies kept for replay — compression, storage, retention.

Owns:
  `codec` — content addressing (sha256), zstd compression and retention classes (pure).
  `store` — write a snapshot on every network fetch; load bodies for replay.
  `retention` — expired snapshots go, then the size cap, then unreferenced blobs.
Depends on: infrastructure (config, pages), shared (infrastructure.db, evidence), observability.metrics; sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat); codec is pure (acquisition-domain-pure).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["codec", "retention", "store"]
