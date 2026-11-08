"""Acquisition · acquisition.pipeline.domain: plain records and pure rules of a research job.

Owns: `variant` — `VariantFacts` (what a stage reads of a car) and `CarVariant` (the record the stores return);
  `rows` — what a page leaves in the database (evidence, claims, area items), as records; `items`, `used_prices` —
  the checks that turn an extraction of a non-spec area into rows; `written` — numbers and dates as pages write
  them; `selection` — the selected value of every attribute from the accepted claims (outliers, the schedule's
  interval) and the gearbox / brand positioning votes; `hits` — accepted sources per domain for the section minimum.
Must not depend on: storage, the network, the application layer.
Public API: the modules in __all__.
"""

__all__ = ["hits", "items", "rows", "selection", "used_prices", "variant", "written"]
