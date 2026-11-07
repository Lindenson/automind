"""A tapped option: the reply is one of the options offered under the pending question (spec 007 F), applied by code
without the interpreter."""

from __future__ import annotations

from automind.chat.application.services.interpretation.contracts import ReplyWords
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile


def picked_option(case: CaseFile, text: str, words: ReplyWords) -> tuple[CaseFile, list[str]] | None:
    """(the case with the option applied, the change log), or None when the reply is not an offered option. "Yes"
    takes a proposed option; "choose for me" / "go ahead" lets the hub choose."""
    return intake.pick(case, text, gearbox_words=dict(words.gearbox_words), yes=words.yes_or_no(text) == "yes",
                       choose=words.choose_for_me(text) or words.go_ahead(text))  # fmt: skip
