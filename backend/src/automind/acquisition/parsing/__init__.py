"""Acquisition · acquisition.parsing: how a page becomes raw claims — declarative site readers and the model readers.

Flow:
    page (HTML) ──► readers.registry (running spec per domain) ──► readers.interpreter ──► rows ──┐
         │                 │  tally: site counts, fingerprints, zero streaks → infrastructure        ├─► pipeline
         └── no reader / too few rows ──► extraction.extract (model, area schema) ──► claims ──────┘   validate
    normalise: cell text → (number, unit), labels, text folding, fuel / gearbox / litres from names and values.

Owns:
  `readers` — ParserSpec (the only form in which a site reader can change), its check, the fixed interpreter, the
    page fingerprint, the live `ParserRegistry` over its ports, the v1 migration and the v1 reference reader.
  `extraction` — the extractor, relevance and validator roles: answer schemas (`contracts`), areas and prompts
    (`areas`), the calls (`extract`).
  `normalise` — text → values the domain unit layer reads; patterns and word tables by concept.
  `infrastructure` — the parser store, the reading log, the v1 specs from the config files, `wiring`
    (`live_readers()`, `parser_registry()`, `yaml_registry()`, `parser_store()`).
Depends on: domain (drift), gates (the shadow feed, wiring only), worker (the doctor's queue, parser store only),
  infrastructure (config), shared (db, config, contracts, evidence, vehicle); pydantic, selectolax, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat); readers.spec, interpreter, fingerprint and normalise
  are pure (acquisition-domain-pure).
Public API: the modules of the subpackages (callers import from them).
"""

__all__: list[str] = ["extraction", "infrastructure", "normalise", "readers"]
