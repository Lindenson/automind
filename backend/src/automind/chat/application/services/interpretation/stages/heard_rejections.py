"""Stage heard_rejections (spec 013 S2, T021): the rejections the model read from the message ("not the E-Class",
"you did not find the C-Class"), kept only when code can stand behind them — the car exists, the person's words are
in the latest message, and the value rejected is the car's current one (or left to the current one). A rejection of
something the car is not, or of the very thing the person says they want, is dropped: it would reject the wrong
thing."""

from __future__ import annotations

from automind.chat.application.services.interpretation.contracts import Interpretation
from automind.chat.domain.case import CarRejection, CaseFile, current_value
from automind.chat.domain.identification.rejection import same_value

MIN_EVIDENCE = 3  # characters of the person's words a rejection needs


def heard_rejections(case: CaseFile, i: Interpretation, user_text: str) -> Interpretation:
    """The interpretation with only the rejections that pass the checks (unchanged when it has none)."""
    refs = i.delta.rejections
    if not refs:
        return i
    kept = [r for r in refs if _stands(case, r, user_text)]
    if len(kept) == len(refs):
        return i
    return i.model_copy(update={"delta": i.delta.model_copy(update={"rejections": kept})})


def _stands(case: CaseFile, r: CarRejection, user_text: str) -> bool:
    car = next((c for c in case.cars if c.key == r.target_key), None)
    if car is None or not _in_message(r.evidence, user_text):
        return False
    now = current_value(car, r.level)
    if not now or (r.value and not same_value(r.value, now)):
        return False  # nothing there to reject, or the model names a value the car does not have
    return not same_value(r.wanted, now)  # "you did not find the C-Class" while the car is the C-Class


def _in_message(words: str, text: str) -> bool:
    w, t = " ".join(words.lower().split()), " ".join(text.lower().split())
    return len(w) >= MIN_EVIDENCE and w in t
