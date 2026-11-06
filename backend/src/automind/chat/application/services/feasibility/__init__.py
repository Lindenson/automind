"""Chat · chat.application.services.feasibility: can the person's budget, running-cost and usage needs be met?

Owns: `feasibility` — gathers validated facts per car, runs the pure domain.assessment.feasibility rules,
  persists the result (`FeasibilityStore`) and builds the `feasibility` block.
Flow: `needs_of(case)` → `car_facts` → `evaluate` → `persist` → `block`.
Depends on: chat.domain (assessment, case, cost, intake), chat.application.services.report.
Must not depend on: chat.dialog, delivery.web, sqlalchemy, langgraph.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["feasibility"]
