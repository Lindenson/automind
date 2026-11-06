"""Acquisition · acquisition.parsing: declarative, versioned site parsers read by one fixed interpreter.

Owns:
  `spec` — ParserSpec: the only form in which a site reader can change (pure).
  `interpreter` — the fixed interpreter that reads a page with a spec (pure).
  `fingerprint` — page structure fingerprint for drift (pure).
  `store` — parser versions in the database: running versions, zero streaks, degrade.
  `registry` — the live site readers: the running spec version per domain.
  `migrate_v1` — today's site readers become version 1 of their specs; `legacy` — the v1 readers, test reference only.
Flow: registry (running spec per domain) → interpreter.read(page) → rows for the pipeline's parse stage.
Depends on: domain, infrastructure (config, overrides), gates (shadow), worker (queue), shared (infrastructure.db,
  config, contracts, evidence, vehicle); pydantic, selectolax, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
  spec, interpreter and fingerprint are pure (acquisition-domain-pure).
Public API: the modules in __all__ (callers import from them).
Note: store and registry reach up into worker.queue and gates.shadow (lazy imports).
"""

__all__: list[str] = ["fingerprint", "interpreter", "legacy", "migrate_v1", "registry", "spec", "store"]
