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
    """What the turn does next: its kind and what it concerns. Built by the policy's rules through the factories
    below (one per kind), so a rule reads as the action it takes; `reason` is free text for people, never compared."""

    kind: ActionKind
    questions: list[QuestionKind] = Field(default_factory=list)
    cars: list[str] = Field(default_factory=list)  # car keys the action concerns
    nothing_new: bool = False
    profile: bool = False  # single-car profile report (FR-012)
    over_cap: bool = False  # estimate exceeds the hard cap: research will stop at the cap
    reason: str = ""

    @classmethod
    def answer_general(cls, reason: str) -> Action:
        """A general answer: no car to compare, or a question about cars in general."""
        return cls(kind="ANSWER_GENERAL", reason=reason)

    @classmethod
    def ask(cls, questions: list[QuestionKind], cars: list[str], reason: str) -> Action:
        """Questions (by kind) about the cars named by key."""
        return cls(kind="ASK", questions=questions, cars=cars, reason=reason)

    @classmethod
    def select_candidates(cls, reason: str) -> Action:
        """No car named but a need and a budget: propose cars."""
        return cls(kind="SELECT_CANDIDATES", reason=reason)

    @classmethod
    def confirm_intake(cls, cars: list[str], *, over_cap: bool, reason: str) -> Action:
        """The intake card: the cars, the profile and the research cost, confirmed together."""
        return cls(kind="CONFIRM_INTAKE", cars=cars, over_cap=over_cap, reason=reason)

    @classmethod
    def confirm_variants(cls, cars: list[str], reason: str) -> Action:
        """The versions of these cars, confirmed by the person."""
        return cls(kind="CONFIRM_VARIANTS", cars=cars, reason=reason)

    @classmethod
    def confirm_cost(cls, cars: list[str], *, over_cap: bool, reason: str) -> Action:
        """The research cost for these cars, confirmed before research."""
        return cls(kind="CONFIRM_COST", cars=cars, over_cap=over_cap, reason=reason)

    @classmethod
    def research(cls, cars: list[str], reason: str) -> Action:
        """Research the data these cars lack."""
        return cls(kind="RESEARCH", cars=cars, reason=reason)

    @classmethod
    def feasibility(cls, reason: str) -> Action:
        """Say that the request does not fit the person's budget or needs before any report."""
        return cls(kind="FEASIBILITY", reason=reason)

    @classmethod
    def answer_from_context(cls, reason: str, *, nothing_new: bool = False, profile: bool = False) -> Action:
        """An answer from the validated data; `nothing_new`: the case is as at the last report."""
        return cls(kind="ANSWER_FROM_CONTEXT", nothing_new=nothing_new, profile=profile, reason=reason)

    @classmethod
    def report(cls, reason: str, *, profile: bool = False) -> Action:
        """The report; `profile`: a single-car profile."""
        return cls(kind="REPORT", profile=profile, reason=reason)

    @classmethod
    def rescore(cls, reason: str) -> Action:
        """Recompute scores, cost and verdict from the data already validated."""
        return cls(kind="RESCORE", reason=reason)
