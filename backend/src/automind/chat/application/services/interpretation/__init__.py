"""Chat · chat.application.services.interpretation: reads the person's message and applies it to the case; words the
questions back.

Owns: `service` — `InterpretationService.read()` (a button, a tapped option, or the model) and `.apply()` (the
  stages in order); `contracts` — `Interpretation`, `Preset`, `Reading`, `Applied`, the state shapes and the
  `ReplyWords` port (the dialog's reading of short replies); `interpret` — the model proposes a typed case delta,
  code checks it (`InterpretError` instead of a guess); `stages/` — the pure steps of applying a message (option
  picked, make to choose from, safety net for named cars, a brand explained, the person's facts and figures, the
  pending question answered); `ask` — up to 3 clarifying questions chosen by code from templates, phrased by the
  model in the person's language, plus intake questions and quick replies (S9d moves it out).
Flow: the dialog's interpret node calls `read`, the apply_delta node calls `apply` and saves the case it returns.
Depends on: chat.domain (case, intake, identification, understanding), chat.application.ports, shared.contracts.
Must not depend on: chat.dialog, delivery.web, sqlalchemy, langgraph.
Public API: `InterpretationService`, the contracts; `ask` and `interpret` as modules.
"""

from automind.chat.application.services.interpretation.contracts import (
    Applied,
    Interpretation,
    InterpretError,
    Preset,
    Reading,
    ReplyWords,
)
from automind.chat.application.services.interpretation.service import ApplyRequest, InterpretationService

__all__ = [
    "Applied",
    "ApplyRequest",
    "InterpretError",
    "Interpretation",
    "InterpretationService",
    "Preset",
    "Reading",
    "ReplyWords",
]
