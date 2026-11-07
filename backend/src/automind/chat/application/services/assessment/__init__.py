"""Chat · chat.application.services.assessment: what code knows about the case's cars before the policy decides —
the catalogue look-up per car and the research plan with its cost.

Owns: `service` — `AssessmentService.cars()` (the comparison level, every car checked again, looked up and
  auto-resolved) and `.plan()` (the research plan from what earlier research left, its cost, a declined plan, the
  feasibility checks, the plan's warnings); `contracts` — `CarsAssessed`, `PlanRequest`, `PlanHistory`, `Planned`,
  the state shape and the `PlanWording` port; `stages/` — car_checked, research_plan, warnings.
Flow: the dialog's assess node calls `cars`, saves the case when it changed, then calls `plan`.
Depends on: chat.domain (case), chat.application.ports (ResearchHistory, Estimator, Clock, MarketFacts),
  services.identification (assessment, revalidation), services.feasibility, shared.research_order.
Must not depend on: chat.dialog, acquisition.api (the research history is a port), sqlalchemy, langgraph.
Public API: the names in __all__.
"""

from automind.chat.application.services.assessment.contracts import CarsAssessed, Planned, PlanRequest
from automind.chat.application.services.assessment.service import AssessmentService

__all__ = ["AssessmentService", "CarsAssessed", "PlanRequest", "Planned"]
