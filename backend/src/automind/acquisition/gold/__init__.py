"""Acquisition · acquisition.gold: gold (reference) values from open datasets, the reference set and user challenges.

Owns:
  `loaders` — dataset readers (EEA CO2, EEA OBFCM, RDW, reference set) → DatasetRow.
  `domain` — pure matching of dataset rows to a catalogue variant, and registered versions of a model.
  `load` — CLI `python -m automind.acquisition.gold.load`: load a dataset into gold values.
  `repo` — gold persistence (datasets, values, challenge gold); `versions` — registered versions (offline first).
Flow: load → loaders.fetch_rows → domain.match → repo.replace.
Depends on: infrastructure.config, shared (infrastructure.db, config, vehicle); sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
Note: load.py borrows the research-time `fuel_of` from pipeline.validate.
"""

__all__: list[str] = ["domain", "load", "loaders", "repo", "versions"]
