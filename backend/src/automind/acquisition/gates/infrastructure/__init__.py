"""Acquisition · acquisition.gates.infrastructure: the stores and measures behind the gates' ports, and their wiring.

Owns: `change_store` (`acq_changes`), `candidates` (the candidate object of a proposal), `objects` (activate,
  restore, drop per kind), `experiments` (`acq_experiments`, pinned pages), `lever_state`, `page_reading` (stored
  pages read the live way, metrics), `measure` (`PageMeasure`), `measure_extractor`, `relevance_pages`,
  `relevance_measure` (`RelevancePages`), `engine_ports` (events, budgets, queue, clock, the journal's gauges),
  `wiring` (`change_journal()`, `replay_gate()`, `shadow_gate()`, `watch()`).
Depends on: acquisition.gates.application (the ports), agents (levers, budget), parsing, pipeline, replay, snapshots,
  worker, acquisition.infrastructure, shared.infrastructure.
Public API: the modules in __all__.
"""

__all__ = ["candidates", "change_store", "engine_ports", "experiments", "lever_state", "measure", "measure_extractor",
           "objects", "page_reading", "relevance_measure", "relevance_pages", "wiring"]  # fmt: skip
