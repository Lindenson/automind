"""Chat · chat.application.services.report.facts: what the report reads of a car, before any block is built.

Owns: `car` — the car dict loaded from acquisition.api's read model and its accessors (values, prices, warranty,
  the make's facts, claim sources); `display` — the specification rows and how a value is written; `quality` —
  reliability and reviews (severity rules installed at startup), engineering completeness; `scoring_inputs` —
  `CarFacts` for the criteria and the insight values; `race` — drag race inputs and run; `retention` — value kept
  after 3 and 5 years.
Flow: `car.load_car` → the other modules read the car dict.
Depends on: chat.domain, acquisition.api, shared.evidence, shared.vehicle. Must not depend on: the blocks, chat.dialog.
Public API: the modules in __all__.
"""

__all__ = ["car", "display", "quality", "race", "retention", "scoring_inputs"]
