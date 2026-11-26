"""The answer to a confirmation (the intake card, the variants proposal): what the button sent, as a closed set
(spec 013 T012). Only a button id confirms; typed words are never read here — they go to the interpreter, so a typed
"нет" can never confirm the cars it rejects.

    button id                      CardChoice    argument
    "yes" / "run" / "confirm" / …  CONFIRM       —   ("choose" on a proposal: take it)
    "stop"                         STOP          —   (the cars kept, the research declined)
    "skip"                         SKIP          —
    "option:<car>:<variant id>"    OPTION        "<car>:<variant id>"
    "remove:<car>"                 REMOVE        "<car>"
    "edit_field"                   EDIT_FIELD    —   (a chip on the card)
    typed text, "text", "edit"     TEXT          —
    anything else                  OTHER         the id   (never confirms: read as words)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CardChoice(StrEnum):
    """What a confirmation's answer is."""

    CONFIRM = "confirm"
    STOP = "stop"
    SKIP = "skip"
    OPTION = "option"
    REMOVE = "remove"
    EDIT_FIELD = "edit_field"
    TEXT = "text"
    OTHER = "other"


CONFIRM_IDS = frozenset({"yes", "run", "confirm", "continue", "choose"})  # "choose": take the proposal
_PLAIN = {"stop": CardChoice.STOP, "skip": CardChoice.SKIP, "edit_field": CardChoice.EDIT_FIELD,
          "text": CardChoice.TEXT, "edit": CardChoice.TEXT}  # fmt: skip
_WITH_ARG = {"option": CardChoice.OPTION, "remove": CardChoice.REMOVE}


@dataclass(frozen=True)
class CardAnswer:
    """A confirmation's answer: its kind, the id's argument (`option:`/`remove:`) and the typed words, if any."""

    kind: CardChoice
    arg: str = ""
    text: str = ""


def card_answer(resume: Mapping[str, object]) -> CardAnswer:
    """The answer the resume payload carries (`choice`: the button id; `text`: typed words)."""
    choice = str(resume.get("choice") or "")
    text = str(resume.get("text") or "")
    if not choice:
        return CardAnswer(CardChoice.TEXT if text else CardChoice.OTHER, text=text)
    if choice in CONFIRM_IDS:
        return CardAnswer(CardChoice.CONFIRM, text=text)
    if choice in _PLAIN:
        return CardAnswer(_PLAIN[choice], text=text)
    head, sep, arg = choice.partition(":")
    if sep and head in _WITH_ARG:
        return CardAnswer(_WITH_ARG[head], arg, text)
    return CardAnswer(CardChoice.OTHER, choice, text or choice)
