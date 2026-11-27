"""Spec 013 T005: the harness ceiling — an interpreter that returns, in the old labels, what each case expects.

Run through the same old path, it shows what the old labels and this harness can score at best: the request,
the language and the relation are perfect, the delta is empty (no changes, no rejections). A field below 100 % here
is a limit of the old schema or of the harness (no identification or assessment), not of the model.
"""

from __future__ import annotations

from typing import TypeVar

from automind.chat.application.services.interpretation.contracts import Interpretation
from tests.eval.understanding.schema import Case, Expected

T = TypeVar("T")
_REQUEST_OF_GOAL = {"compare": "compare", "single": "single", "follow_up": "follow_up_question",
                    "change_priorities": "weights_change", "research_more": "research_more",
                    "ask_general": "general_question", "critique": "critique", "stop": "chitchat"}  # fmt: skip
_REQUEST_OF_ANSWER = {"yes": "confirm_yes", "no": "confirm_no", "choose_for_me": "choose_for_me"}
_RELATION_OF_REACTION = {"complaint": "complaint", "correction": "correction", "rephrase": "rephrase",
                         "thanks": "thanks"}  # fmt: skip
_MARK = "LATEST USER MESSAGE:\n"


class OracleLLM:
    """The `LLM` port answering the interpreter with the expected labels of the case whose message it reads."""

    def __init__(self, cases: list[Case]) -> None:
        self.by_message = {c.message: c.expect for c in cases}

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        e = self.by_message[user.split(_MARK, 1)[1]]
        return schema.model_validate(labels(e).model_dump())  # type: ignore[attr-defined, no-any-return]

    async def text(self, role: str, system: str, user: str) -> str:
        return ""


def labels(e: Expected) -> Interpretation:
    """The old labels of an expectation (understanding-spec §4 read backwards)."""
    if e.answer is not None and e.answer.kind.value in _REQUEST_OF_ANSWER:
        request = _REQUEST_OF_ANSWER[e.answer.kind.value]
    elif e.goals:
        request = _REQUEST_OF_GOAL[e.goals[0].kind.value]
    else:
        request = "compare" if e.answer is not None else "chitchat"
    relation = _RELATION_OF_REACTION.get(e.reaction.value, "continues")
    return Interpretation.model_validate({"request": request, "language": e.language.value, "relation": relation})
