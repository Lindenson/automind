"""Chat · chat.application.services.report: builds the report — numbers, blocks and cards — from cached data only.

Owns: `compose` — loads cached car data, computes metrics, race, scores and costs, builds UI blocks (also used by
  the MCP server); `electric_block` — the electric section; `intake_card` — the intake confirmation card and its
  edits; `car_view` — what the person sees of each car and its "Change" options.
Depends on: chat.domain (assessment, cost, verdict, identification), acquisition.api, shared.evidence,
  shared.vehicle. Must not depend on: chat.dialog, delivery.web, langgraph.
Note: `compose` (1224 lines) reads the DB with sqlalchemy (.importlinter exception); split into facts/ and blocks/
  behind a `CarRepository` port in S8.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["car_view", "compose", "electric_block", "intake_card"]
