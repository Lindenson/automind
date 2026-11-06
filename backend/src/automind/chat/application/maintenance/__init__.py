"""Chat · chat.application.maintenance: one-shot, idempotent data repair run by `scripts/repair-data.sh`.

Owns: `repair` — `repair_claims` (re-check spec claims with today's rules), `reclassify_sources`,
  `merge_duplicates` (fold catalog duplicates).
Depends on: acquisition.api, shared.evidence, shared.vehicle, shared.infrastructure (db), sqlalchemy.
Must not depend on: chat.dialog, delivery.web.
Note: it repairs engine-owned data (claims, catalog, sources), not chat data; planned to move to the acquisition
  engine (T021) and is still here.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["repair"]
