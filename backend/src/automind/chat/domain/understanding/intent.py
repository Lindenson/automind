"""What a message means, as independent fields (spec 013 §D1, understanding-spec §4): the one input the policy will
read from S4 on.

`Understanding` is what the model returns for typed words (structured output); `UiAction` is what a button sends
(no model call); `Intent` is what the resolver makes of either, with every correction it made listed as an
`Override`. The fields do not exclude each other: "да, но дизель" is an answer (yes) and a fact (diesel); "да, и
добавь Hyundai" is an answer, a goal and a fact.

Rejections ("not the E-Class", spec 013 S2) are part of `case_changes` (`CaseDelta.rejections`): one owner, read
through `Intent.rejections`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from automind.chat.domain.case import CarRejection, CaseDelta


class AnswerKind(StrEnum):
    """How a message answers the open question: an offered option, a value of its own, yes, no, or "choose for me"."""

    OPTION = "option"
    VALUE = "value"
    YES = "yes"
    NO = "no"
    CHOOSE_FOR_ME = "choose_for_me"


class GoalKind(StrEnum):
    """What the person wants to achieve (understanding-spec §4, + `stop` of spec 013 §D1)."""

    COMPARE = "compare"
    SINGLE = "single"
    FOLLOW_UP = "follow_up"
    CHANGE_PRIORITIES = "change_priorities"
    RESEARCH_MORE = "research_more"
    ASK_GENERAL = "ask_general"
    CRITIQUE = "critique"
    STOP = "stop"


class Reaction(StrEnum):
    """How the person took the bot's previous answer."""

    THANKS = "thanks"
    COMPLAINT = "complaint"
    CORRECTION = "correction"
    REPHRASE = "rephrase"


class IntentSource(StrEnum):
    """Where an intent comes from: typed words, a button, or the system (a report saved — never a person's intent)."""

    TEXT = "text"
    UI = "ui"
    SYSTEM = "system"


class UiActionKind(StrEnum):
    """What a button does (understanding-spec §3); `complain` and `quit` come with S6."""

    PICK_OPTION = "pick_option"
    CONFIRM = "confirm"
    DECLINE = "decline"
    CHOOSE_FOR_ME = "choose_for_me"
    EDIT_CAR = "edit_car"
    RESEARCH_MORE = "research_more"
    PANEL_EDIT = "panel_edit"


class PendingAnswer(BaseModel):
    """The message answers the open bot question PENDING."""

    model_config = ConfigDict(frozen=True)

    pending_id: str = Field(description="The id of the open question (PENDING.id), copied exactly")
    kind: AnswerKind = Field(
        description="option: picks one of PENDING.options; value: gives its own value for the question (a year, an "
        "engine, 'diesel'); yes / no: agrees or refuses; choose_for_me: lets the assistant pick ('any', 'любой')"
    )
    option_id: str | None = Field(default=None, description="Only with kind option: an id from PENDING.options")
    evidence: str = Field(description="The person's words of the MESSAGE this answer comes from, verbatim")


class Goal(BaseModel):
    """One thing the person wants done; a message may carry several, in the order written."""

    model_config = ConfigDict(frozen=True)

    kind: GoalKind = Field(
        description="compare: compare or recommend cars; single: about one car; follow_up: a question about the "
        "cars or the report already discussed; change_priorities: what matters to them changed; research_more: "
        "find missing data, search again, update the report; ask_general: general car knowledge ('what is DSG?'); "
        "critique: unhappy with the report and says what is wrong; stop: end the current search or question "
        "('отменяй поиск', 'хватит', 'stop')"
    )
    focus_cars: list[str] = Field(default_factory=list, description="Car keys (car#N) the goal is about; [] = all")
    focus_areas: list[str] = Field(
        default_factory=list,
        description="research_more / critique: areas named (specs, price, maintenance, reliability, reviews, "
        "measured, engineering, manufacturer, depreciation); [] = all",
    )
    question: str | None = Field(default=None, description="follow_up / ask_general: the question itself")


class Understanding(BaseModel):
    """The model's reading of one message: four independent questions, answered separately."""

    language: str = Field(description="ISO 639-1 code of the MESSAGE (ru, es, en …)")
    answer_to_pending: PendingAnswer | None = Field(
        default=None, description="Set only when the MESSAGE answers PENDING; null when PENDING is null"
    )
    goals: list[Goal] = Field(default_factory=list, description="What the person wants, in the order written")
    reaction: Reaction | None = Field(
        default=None,
        description="How the MESSAGE takes the assistant's LAST ANSWER: thanks, complaint (unhappy: 'useless', "
        "'плохо'), correction (says something was wrong: 'no, I meant…'), rephrase (asks the same again because the "
        "answer missed it); null when none of these",
    )
    case_changes: CaseDelta = Field(
        default_factory=CaseDelta, description="Facts the MESSAGE states, as changes of the CASE FILE"
    )
    persona_evidence: str | None = Field(
        default=None, description="The person's verbatim words that show who they are; required for set_persona"
    )
    constraints_evidence: list[str] = Field(
        default_factory=list,
        description="Verbatim words of the MESSAGE holding the numbers of set_budget, set_running_cost_limit, "
        "set_needs",
    )


class UiAction(BaseModel):
    """What a button sends instead of words; the model is never called for it."""

    model_config = ConfigDict(frozen=True)

    kind: UiActionKind
    pending_id: str | None = None
    option_id: str | None = None
    car_key: str | None = None
    field: str | None = None
    value: str | None = None
    focus_cars: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)


class Override(BaseModel):
    """One correction the resolver made to the understanding: the rule, the field, before, after, why."""

    model_config = ConfigDict(frozen=True)

    rule: str
    field: str
    before: object = None
    after: object = None
    why: str


class Intent(BaseModel):
    """The resolved meaning of one message or button: the policy's one input (from S4)."""

    source: IntentSource
    language: str
    answer_to_pending: PendingAnswer | None = None
    goals: list[Goal] = Field(default_factory=list)
    reaction: Reaction | None = None
    case_changes: CaseDelta = Field(default_factory=CaseDelta)
    overrides: list[Override] = Field(default_factory=list)  # empty: the model or the button taken as it was

    @property
    def rejections(self) -> list[CarRejection]:
        """What the person rejects about a car's identity (spec 013 §D1), kept in `case_changes`."""
        return self.case_changes.rejections
