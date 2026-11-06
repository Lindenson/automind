"""Chat · chat.application: applies the domain rules to stored data through ports — the chat's use-case layer.

Owns: `ports` — the interfaces it needs (`Ports` bundle: case, turn, job, message repos, event bus, LLM, clock …);
  `services` — identification, interpretation, report, feasibility; `usecases` — actions started from the web
  (challenge a value, delete chats); `maintenance` — data repair.
Depends on: chat.domain, shared.contracts, acquisition.api. Must not depend on: chat.dialog, delivery.web,
  chat.infrastructure, shared.infrastructure, langgraph, fastapi, sqlalchemy.
Note: compose, resolve, lineup, challenge and repair still use the DB directly (`ignore_imports` in .importlinter);
  they go behind ports in S7–S9.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["maintenance", "ports", "services", "usecases"]
