"""Contracts of the interpretation service: what the model proposes for one message (`Interpretation`), the request a
button sends instead of words (`Preset`), what reading and applying a message give back (`Reading`, `Applied`), and the
port the service needs from the dialog — the reply words in the person's language (`ReplyWords`).

`Preset` is a `TypedDict` because it lives in the graph state, which holds plain data only (code-shape.md "Dialog
state"); what `Reading` and `Applied` write into the turn state is the dialog's node contract (`dialog.nodes`)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel, Field

from automind.chat.domain.case import CaseDelta, CaseFile
from automind.chat.domain.decision import RequestKind

Relation = Literal["continues", "rephrase", "correction", "complaint", "thanks", "new_topic"]
AskBack = Literal["rephrase", "which_car"]  # the phrase key of the question asked instead of applying the message
History = list[dict[str, str]]  # the last turns, oldest first: {"role": "user" | "assistant", "text": …}


class InterpretError(ValueError):
    """The model's output could not be read or names a car the case does not have (→ ask the person to rephrase)."""


class Interpretation(BaseModel):
    """What the model reads from one message: the request, the language, how it relates to the previous answer and
    the typed change of the case it states. Code checks it before it is applied (`interpret`)."""

    request: RequestKind = Field(
        description="compare: compare/recommend cars; single: one car; follow_up_question: question about cars "
        "already discussed; weights_change: priorities/what matters changed; correction: user corrects a car or "
        "a fact; research_more: the user asks to find missing data, search again or redo/update the report "
        "('why is there no data for X? find it', 'update the report', 'look deeper'); general_question: general "
        "automotive knowledge; confirm_yes/confirm_no: answer to a pending confirmation; choose_for_me: the user "
        "lets the hub pick the version ('any', 'choose for me', 'любой', 'на твой выбор', 'cualquiera'); "
        "critique: the user is unhappy with the report ('bad', 'useless', 'incomplete', 'плохо', 'фигня', 'malo'), "
        "with focus_cars / focus_areas when they name what is wrong; "
        "chitchat: greetings/other"
    )
    language: str = Field(description="ISO 639-1 code of the user's message, e.g. 'ru', 'en', 'es'")
    relation: Relation = Field(
        default="continues",
        description="How this message relates to the assistant's PREVIOUS answer (spec 010 FR-002): continues = goes "
        "on from it (next step, a question about it, an answer to its question); rephrase = asks the same thing again "
        "in other words because the answer missed it; correction = says the assistant got something wrong ('no, I "
        "meant…', 'not the 250, the 150'); complaint = unhappy with the answer ('useless', 'плохо', 'no sirve'); "
        "thanks = thanks or approval; new_topic = an unrelated new request. First message of a chat: continues.",
    )
    delta: CaseDelta = Field(default_factory=CaseDelta, description="Changes to the case file stated in THIS message")
    persona_evidence: str | None = Field(
        default=None,
        description="Verbatim words the user wrote (this or an earlier message) that show who they are; required "
        "to set_persona",
    )
    focus_cars: list[str] = Field(
        default_factory=list, description="research_more: car keys the user named (empty = all cars)"
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="research_more: research areas the user named (specs, price, maintenance, reliability, "
        "reviews, measured, engineering, manufacturer, depreciation); empty = every area below its minimum",
    )
    constraints_evidence: list[str] = Field(
        default_factory=list,
        description="Verbatim words from the LATEST message that contain the numbers set in set_budget, "
        "set_running_cost_limit or set_needs",
    )


class Preset(TypedDict, total=False):
    """A request a button sends instead of words: "find it" (`kind` research_more, `focus_cars`, `areas`), a car
    edit (`kind` car_edit, `car_key`, `field`, `value`) or a tapped one-tap answer (`kind` pick, `option_id`, spec 013
    T013). `language` is the chat's when the button knows it."""

    kind: str
    language: str | None
    focus_cars: list[str]
    areas: list[str]
    car_key: str
    field: str
    value: str
    option_id: str


@dataclass(frozen=True)
class Reading:
    """One message read: the interpretation, or the question to ask back instead (`ask`, nothing applied).
    `picked`: the message is one of the offered options, applied by code in `apply`."""

    interpretation: Interpretation | None
    language: str | None
    picked: bool = False
    ask: AskBack | None = None


@dataclass(frozen=True)
class Applied:
    """The case after the message: `case` (unchanged when nothing applied), the request as code settled it, the change
    log, the car keys whose pending question the message left unanswered, and whether the case is to be saved
    (`saved`: something changed). `ask`: the delta named a car the case does not have — nothing applied, ask which."""

    case: CaseFile
    request: RequestKind
    changes: list[str] = field(default_factory=list)
    not_understood: list[str] = field(default_factory=list)
    saved: bool = False
    ask: AskBack | None = None


class ReplyWords(Protocol):
    """How a short reply reads in the person's language (implemented by the dialog's `phrases`)."""

    @property
    def gearbox_words(self) -> Mapping[str, str]:
        """A gearbox named in one word ("автомат", "manual") → automatic | manual."""
        ...

    def choose_for_me(self, text: str | None) -> bool:
        """ "Any" / "choose for me": the hub takes the base version."""
        ...

    def go_ahead(self, text: str | None) -> bool:
        """ "Go ahead" / "вперёд к сравнению": move on."""
        ...

    def yes_or_no(self, text: str | None) -> str | None:
        """A short typed answer to a confirmation: "yes", "no", or None."""
        ...

    def guess_language(self, texts: list[str]) -> str:
        """The language of the person's words (for a button request without text)."""
        ...

    def stable_language(self, detected: str | None, current: str, earlier: list[str]) -> str | None:
        """The chat's language with hysteresis: one English model name does not switch a Russian chat."""
        ...
