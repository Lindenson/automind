"""Acquisition · acquisition.drift: daily parser metrics and parser drift detection (worker tasks).

Owns: `daily` — roll_day writes `parser_daily` per parser version; detect flags drift and degrades the version.
Flow: worker `parser_daily` → roll_day (re-read the day's stored pages) → worker `drift` → domain.drift verdict
  → parsing.store.degrade → parser doctor.
Depends on: domain (drift), parsing, snapshots, infrastructure (config, fetch), worker, shared.infrastructure.db.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); run by worker.handlers.
"""

__all__: list[str] = ["daily"]
