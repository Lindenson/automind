"""Acquisition · acquisition.identity_readers.domain: pure rules of the identity readers.

Owns:
  `registered` — IdRow, RegisteredVersion, VersionLimits; `group` (dataset groups → distinct versions of a model),
    `rows_of_keys` (stored EEA group keys → rows), `id_row`.
Depends on: gold.domain (records, text), shared.contracts.
Must not depend on: I/O and frameworks, shared.infrastructure (import-linter acquisition-domain-pure).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["registered"]
