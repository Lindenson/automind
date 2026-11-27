"""The closed value sets of the golden message set (spec 013 T004): languages, sources, coverage categories, and the
`Intent` / `Action` values a case expects (understanding-spec §4; `ActionKind` of `domain.decision` + T041's kind)."""

from __future__ import annotations

from enum import StrEnum


class Lang(StrEnum):
    RU = "ru"
    ES = "es"
    EN = "en"


class Source(StrEnum):
    """Where a case comes from (understanding-spec §8); `t004` = written for a coverage line of T004 itself."""

    SPEC1 = "spec§1"
    PROBLEM_TABLE = "problem-table"
    GOLDEN = "golden"
    INTERPRETER = "interpreter.md"
    PHRASES = "phrases"
    PREPROD_MISS = "preprod-miss"
    PREPROD = "preprod"
    T004 = "t004"


class Category(StrEnum):
    """A coverage line of T004. Pending kinds and sources are derived (`coverage.categories`); the rest are tags."""

    SPEC1 = "spec1"
    PROBLEM_TABLE = "problem_table"
    REJECTION = "rejection"
    STOP = "stop"
    COMPLAINT = "complaint"
    LOOKALIKE_YES = "lookalike_yes"
    LOOKALIKE_NO = "lookalike_no"
    LOOKALIKE_CHOOSE = "lookalike_choose"
    TWO_INTENTS = "two_intents"
    DIESEL_ENGINE_OPEN = "diesel_engine_open"
    DIESEL_ENGINE_CLOSED = "diesel_engine_closed"
    PLAIN_YES = "plain_yes"
    PLAIN_NO = "plain_no"
    CHOOSE_FOR_ME = "choose_for_me"
    QUESTION_DURING_QUESTION = "question_during_question"
    BUTTON_TEXT = "button_text"
    LANGUAGE_HYSTERESIS = "language_hysteresis"
    NO_PENDING = "no_pending"
    PENDING_QUESTIONS = "pending_questions"
    PENDING_CONFIRM_VARIANTS = "pending_confirm_variants"
    PENDING_CONFIRM_COST = "pending_confirm_cost"
    PENDING_CONFIRM_INTAKE = "pending_confirm_intake"
    PENDING_LIMIT = "pending_limit"
    GOLDEN = "golden"
    INTERPRETER_PATCH = "interpreter_patch"
    PHRASES_WORD = "phrases_word"
    PREPROD_MISS = "preprod_miss"


class PendingKind(StrEnum):
    """`Pending.kind` today plus the research-limit question (T031 gives it a pending id)."""

    QUESTIONS = "QUESTIONS"
    CONFIRM_VARIANTS = "CONFIRM_VARIANTS"
    CONFIRM_COST = "CONFIRM_COST"
    CONFIRM_INTAKE = "CONFIRM_INTAKE"
    LIMIT = "LIMIT"


class AnswerKind(StrEnum):
    """`PendingAnswer.kind`."""

    OPTION = "option"
    VALUE = "value"
    YES = "yes"
    NO = "no"
    CHOOSE_FOR_ME = "choose_for_me"


class GoalKind(StrEnum):
    """understanding-spec §4 `GoalKind` + `stop` (spec 013 §D1)."""

    COMPARE = "compare"
    SINGLE = "single"
    FOLLOW_UP = "follow_up"
    CHANGE_PRIORITIES = "change_priorities"
    RESEARCH_MORE = "research_more"
    ASK_GENERAL = "ask_general"
    CRITIQUE = "critique"
    STOP = "stop"


class ReactionExpect(StrEnum):
    """`Reaction` values, `none` (must be absent) and `any` (not checked)."""

    THANKS = "thanks"
    COMPLAINT = "complaint"
    CORRECTION = "correction"
    REPHRASE = "rephrase"
    NONE = "none"
    ANY = "any"


class ActionKind(StrEnum):
    """`domain.decision.ActionKind` + `ANSWER_AND_REASK` (added by 013 T041 on spec 015's `ROUTES`)."""

    RESCORE = "RESCORE"
    ANSWER_GENERAL = "ANSWER_GENERAL"
    ASK = "ASK"
    CONFIRM_VARIANTS = "CONFIRM_VARIANTS"
    CONFIRM_COST = "CONFIRM_COST"
    RESEARCH = "RESEARCH"
    ANSWER_FROM_CONTEXT = "ANSWER_FROM_CONTEXT"
    REPORT = "REPORT"
    FEASIBILITY = "FEASIBILITY"
    CONFIRM_INTAKE = "CONFIRM_INTAKE"
    SELECT_CANDIDATES = "SELECT_CANDIDATES"
    ANSWER_AND_REASK = "ANSWER_AND_REASK"


NEW_ACTION_KINDS: frozenset[ActionKind] = frozenset({ActionKind.ANSWER_AND_REASK})  # not in the domain yet
