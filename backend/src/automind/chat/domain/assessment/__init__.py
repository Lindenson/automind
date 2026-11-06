"""Chat · chat.domain.assessment: scoring and checking the cars against the person's needs — numbers from code.

Owns: `criteria` — criteria dictionary and 0–100 scores; `weights` — criteria weights (persona, profile, wishes,
  manual); `metrics` — physical car metrics; `dragrace` — drag race simulation; `feasibility` — budget, running cost
  and usage checks per car; `reliability` — known issues merged by severity; `reviews` — review summaries;
  `ask_value` / `profile_gaps` — which unknown about the person would change the answer.
Depends on: chat.domain.case. Must not depend on: sqlalchemy, langgraph, fastapi, chat.application, chat.dialog.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = [
    "ask_value",
    "criteria",
    "dragrace",
    "feasibility",
    "metrics",
    "profile_gaps",
    "reliability",
    "reviews",
    "weights",
]
