"""Chat · chat.application.services.assessment.stages: the named steps of assessing the case's cars.

Owns: `car_checked` (a car's version checked again, the car looked up and auto-resolved), `research_plan` (the
  case-driven plan from what earlier research left; pure), `warnings` (the plan's warnings, once per turn; pure).
Flow: `car_checked` for every car in `AssessmentService.cars`; `research_plan`, then `warnings` in `.plan`.
Depends on: chat.domain (case), services.identification, shared.research_order, the package's `contracts`.
Must not depend on: chat.dialog, acquisition.api, storage.
Public API: the modules in __all__.
"""

__all__ = ["car_checked", "research_plan", "warnings"]
