"""Chat · chat.application.services.report.stages: the named steps of computing a report.

Owns: `used_cars` (a used car's age, used price, warranty), `ownership` (costs per year and over the period, energy
  warnings), `case_notices` (young generations, cars not sold in Spain), `scores` (criteria scores; the same data
  for another profile), `verdict` (insights → verdict card, limits, counterfactual, labels, break-even),
  `assemble` (the blocks), `present` (persona order, suggestions, the writer's facts).
Flow: called in this order by `service.ReportService.run`.
Depends on: report.facts, report.blocks, report.contracts, chat.domain, acquisition.api.
Must not depend on: chat.dialog (the wording comes through `contracts.ReportWording`), the service.
Public API: the modules in __all__.
"""

__all__ = ["assemble", "case_notices", "ownership", "present", "scores", "used_cars", "verdict"]
