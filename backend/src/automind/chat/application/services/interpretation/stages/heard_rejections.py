"""Stage heard_rejections (spec 013 S2, T021): the rejections the model read from the message ("not the E-Class",
"you did not find the C-Class"), kept only when code can stand behind them (`understanding.checks.heard_rejections`:
the car exists, the person's words are in the latest message, the value rejected is the car's current one and not
the one they want)."""

from __future__ import annotations

from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.application.services.understanding import checks
from automind.chat.domain.case import CaseFile


def heard_rejections(case: CaseFile, i: Interpretation, user_text: str) -> Interpretation:
    """The interpretation with only the rejections that pass the checks (the same object when all pass)."""
    d, _ = checks.heard_rejections(case, i.delta, user_text)
    return i if d is i.delta else i.model_copy(update={"delta": d})
