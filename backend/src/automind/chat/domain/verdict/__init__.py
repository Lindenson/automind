"""Chat · chat.domain.verdict: the code-built conclusion of a comparison — which differences matter and who wins.

Owns: `insights` — meaningful differences between the cars (tiers, ties, trade-offs);
  `verdict` — the pick or a tie, reasons, confidence and what would change it (the model only phrases it);
  `suggestions` — next steps after a report; `report_layout` — block order per persona.
Flow: criteria scores + insights + missing data → `verdict.build` → `suggestions.build`; blocks → `report_layout`.
Depends on: chat.domain.assessment, chat.domain.cost. Must not depend on: sqlalchemy, langgraph, fastapi,
  chat.application, chat.dialog.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["insights", "report_layout", "suggestions", "verdict"]
