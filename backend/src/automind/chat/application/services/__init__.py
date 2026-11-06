"""Chat · chat.application.services: the chat's services — each one does one job of a turn for the dialog nodes.

Owns: `identification` — which exact car the person means; `interpretation` — reading the message, asking
  questions; `report` — the computed report blocks and cards; `feasibility` — whether the constraints can be met.
Depends on: chat.domain, chat.application.ports, acquisition.api. Must not depend on: chat.dialog, delivery.web,
  chat.infrastructure, langgraph, fastapi.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["feasibility", "identification", "interpretation", "report"]
