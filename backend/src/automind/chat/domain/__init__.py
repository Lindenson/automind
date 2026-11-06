"""Chat · chat.domain: pure, deterministic rules of the conversation — no database, no web, no LLM.

Owns: `case` — the case file and its delta; `intake` — the intake loop and text parsers;
  `identification` — settling a car, the version ladder, used-car facts; `cost` — energy, TCO, incentives,
  turn cost; `assessment` — criteria, weights, metrics, drag race, feasibility, reliability, reviews;
  `verdict` — insights, verdict, suggestions, block order; `policy` — the action the hub takes next.
Depends on: pydantic, shared.vehicle.identity. Must not depend on: langgraph, langchain, fastapi, sqlalchemy,
  httpx, chat.application, chat.dialog, chat.infrastructure, shared.infrastructure, acquisition internals.
Note: acquisition.pipeline imports `intake` and `identification.used`, so part of this is shared vehicle knowledge
  (markets cluster → shared.vehicle in S5).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["assessment", "case", "cost", "identification", "intake", "policy", "verdict"]
