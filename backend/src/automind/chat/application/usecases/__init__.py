"""Chat · chat.application.usecases: actions the web layer starts directly, outside the turn graph.

Owns: `chats` — `delete_chats`: cancel the running turn, then remove every chat-scoped record (ports only);
  `challenge` — "this is wrong" on a value: re-check its claims and report CONFIRMED / CORRECTED / ….
Depends on: chat.application.ports; `challenge` also acquisition.api, acquisition.registry.api, shared.
Must not depend on: chat.dialog, delivery.web, langgraph, fastapi.
Note: `challenge` still uses the DB directly (.importlinter exception); becomes `ChallengeValue` behind a port in S9.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["challenge", "chats"]
