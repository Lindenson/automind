"""Acquisition · acquisition.pipeline.application: the pipeline's services and the ports of its stores.

Owns: `ports` — `PipelineStores` (variants, evidence, values, verdicts, job book) and
  `PipelineStoreUnavailable`, raised by every store behind them; `selection` — `ValueSelection` (the selected
  values and the gearbox of a variant).
Depends on: acquisition.pipeline.domain, shared (evidence, contracts).
Must not depend on: sqlalchemy, shared.infrastructure, any infrastructure package (the stores are ports).
Public API: the modules in __all__.
"""

__all__ = ["ports", "selection"]
