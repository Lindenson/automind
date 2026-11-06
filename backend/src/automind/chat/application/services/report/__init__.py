"""Chat · chat.application.services.report: builds the report — numbers, blocks and cards — from stored data only.

Owns: `facts/` — the car as the report reads it (`car.load_car` over acquisition.api's read model), its display,
  reliability and reviews, scoring inputs, race and value retention; `blocks/` — one module per report block (spec
  table, metric bars, race, sources, data panel, criteria, case summary, engineering, manufacturer, tco,
  reliability, reviews, value retention, electric, car view, intake card); `tco_inputs` — a car's ownership-cost
  inputs; `writer_facts` — the validated facts the writer is given; `computations` — a turn's estimates and race
  kept through the ComputationStore port.
Flow: facts.car.load_car → facts (scoring inputs, race, tco inputs) → domain (scores, costs, insights) → blocks;
  the dialog's compute node orders them (S8b: a ReportService).
Depends on: chat.domain (assessment, cost, verdict, identification), chat.application.ports, acquisition.api,
  shared.evidence, shared.vehicle. Must not depend on: chat.dialog, delivery.web, langgraph, the database.
Public API: the subpackages and modules in __all__ (callers import from them; also used by the MCP server).
"""

__all__ = ["blocks", "computations", "facts", "tco_inputs", "writer_facts"]
