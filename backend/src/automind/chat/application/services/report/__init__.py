"""Chat · chat.application.services.report: builds the report — numbers, blocks and cards — from stored data only.

Owns: `service` — `ReportService.run()`: load → used cars → ownership → notices → scores → verdict → blocks →
  presentation; `contracts` — `Computed`, `CheckInput`, the `ReportWording` port (the dialog's language) and
  `IntakeLog`; `stages/` — the steps; `case_facts` — what the case says (km, years, usage, assumptions);
  `facts/` — the car as the report reads it (`car.load_car` over acquisition.api's read model), its display,
  reliability and reviews, scoring inputs, race and value retention; `blocks/` — one module per report block (spec
  table, metric bars, race, sources, data panel, criteria, case summary, engineering, manufacturer, tco,
  reliability, reviews, value retention, electric, car view, intake card); `tco_inputs` — a car's ownership-cost
  inputs; `writer_facts` — the validated facts the writer is given; `computations` — a turn's estimates and race
  kept through the ComputationStore port.
Flow: the dialog's report and answer nodes call `ReportService(ports, wording, log).run(case, notices, lang)`.
Depends on: chat.domain (assessment, cost, verdict, identification), chat.application.ports, acquisition.api,
  shared.evidence, shared.vehicle. Must not depend on: chat.dialog, delivery.web, langgraph, the database.
Public API: the subpackages and modules in __all__ (callers import from them; also used by the MCP server).
"""

from automind.chat.application.services.report.service import ReportService

__all__ = ["ReportService", "blocks", "case_facts", "computations", "contracts", "facts", "stages", "tco_inputs",
           "writer_facts"]  # fmt: skip
