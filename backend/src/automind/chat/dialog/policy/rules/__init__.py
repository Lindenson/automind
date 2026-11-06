"""Chat · chat.dialog.policy.rules: the rules of the action policy, grouped by the phase they decide.

Owns: `limits`, `general`, `intake`, `confirm`, `research`, `answer` (their order is `chain.RULES`).
Depends on: chat.domain. Must not depend on: the application, infrastructure, langgraph.
Public API: the modules in __all__.
"""

__all__ = ["answer", "confirm", "general", "intake", "limits", "research"]
