"""Chat · chat.domain.decision: what the dialog decides each pass and what it decides against.

Owns: `action` — the action and request kinds, `CarState` (what code knows about a car), `Action` with one factory
  per kind; `config` — `PolicyConfig` (thresholds, pass limit, intake limits). The rules are in chat.dialog.policy.
Depends on: chat.domain.case, chat.domain.intake, pydantic.
Public API: the names in __all__.
"""

from automind.chat.domain.decision.action import Action, ActionKind, CarState, RequestKind
from automind.chat.domain.decision.config import PolicyConfig

__all__ = ["Action", "ActionKind", "CarState", "PolicyConfig", "RequestKind"]
