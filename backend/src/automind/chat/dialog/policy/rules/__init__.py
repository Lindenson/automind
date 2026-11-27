"""Chat · chat.dialog.policy.rules: the rules of the action policy, one module per stage.

Owns: `limits`, `general`, `intake`, `confirm`, `research`, `answer` (their order is `decide.RULES`).
Depends on: chat.domain. Must not depend on: the application, infrastructure, langgraph.
Public API: the modules in __all__.
"""

__all__ = ["answer", "confirm", "general", "intake", "limits", "research"]
