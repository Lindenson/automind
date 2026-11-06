"""What the dialog decides each pass (research R5): the action kinds, the request kinds the interpreter (or code) sets,
what code knows about a car before deciding, and the decided `Action`. Data only — the rules are in
chat.dialog.policy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from automind.chat.domain.case import QuestionKind

ActionKind = Literal[
    "RESCORE",  # spec 007: recompute scores, cost and verdict from the data already validated
    "ANSWER_GENERAL",
    "ASK",
    "CONFIRM_VARIANTS",
    "CONFIRM_COST",
    "RESEARCH",
    "ANSWER_FROM_CONTEXT",
    "REPORT",
    "FEASIBILITY",
    "CONFIRM_INTAKE",
    "SELECT_CANDIDATES",  # spec 007 US7: no car named, but a need and a budget: propose 2–3 cars
]
RequestKind = Literal[
    "compare",
    "single",
    "follow_up_question",
    "weights_change",
    "correction",
    "research_more",
    "general_question",
    "confirm_yes",
    "confirm_no",
    "choose_for_me",
    "critique",
    "chitchat",
    "rescore",  # spec 007 FR-013: an edit in the case panel; set by code (preset), never by the interpreter
    "report_saved",  # spec 007 FR-029: after a turn timeout, the report from the data already saved (code only)
]


class CarState(BaseModel):
    """What code knows about a case car before deciding (catalog lookup + cache freshness)."""

    identity_known: bool = True  # make and model are known
    in_catalog: bool = False
    ambiguous: bool = False  # more than one catalog variant fits
    plausible_generations: int = 0  # generations that fit condition/year (0 = unknown)
    data_fresh: bool = False  # all areas needed by the current criteria are cached and fresh
    gearbox_mixed: bool = False  # accepted values of several gearboxes for one variant (spec 004 FR-028)


class Action(BaseModel):
    kind: ActionKind
    questions: list[QuestionKind] = Field(default_factory=list)
    cars: list[str] = Field(default_factory=list)  # car keys the action concerns
    nothing_new: bool = False
    profile: bool = False  # single-car profile report (FR-012)
    over_cap: bool = False  # estimate exceeds the hard cap: research will stop at the cap
    reason: str = ""
