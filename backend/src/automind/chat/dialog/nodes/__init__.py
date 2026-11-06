"""Chat · chat.dialog.nodes: the turn graph's steps — each reads the state, calls the application, writes back.

Owns: `understand` — load_case, interpret, apply_delta, assess, policy; `identify` — re-identify changed cars;
  `confirm` — ASK, CONFIRM_VARIANTS, CONFIRM_COST, intake (prepare → wait/interrupt → apply);
  `feasibility` — feasibility verdict before the report; `research` — research jobs per car × area with gap rounds;
  `compute` — deterministic numbers and blocks; `report` — report, answer and general answer with the number guard;
Depends on: chat.application.services, chat.domain, chat.dialog (runner, state, phrases, guard), langgraph,
  acquisition.api, shared.infrastructure (config, db session). Must not depend on: delivery.web, sqlalchemy.
Note: `compute` holds pure report helpers (→ report service, S8).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["compute", "confirm", "feasibility", "identify", "report", "research", "understand"]
