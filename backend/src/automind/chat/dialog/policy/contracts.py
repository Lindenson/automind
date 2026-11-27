"""The contracts of the dialog's action policy (spec 015 D1): what is known in one pass (`Situation` with a
`CarFacts` per car), what a rule says (`RuleOutcome`), what the policy returns (`Decision`), and its two errors.

A rule checks the situation against the config and either fires (with an `Action`) or skips (with why); `decide`
asks the rules in order and the first that fires decides. Pure: no I/O, no clock, no settings."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, CarState, PolicyConfig, RequestKind

MAX_QUESTIONS = 3


class Stage(StrEnum):
    """The phase a rule decides, in the order of `RULES`."""

    LIMITS = "limits"
    GENERAL = "general"
    INTAKE = "intake"
    CONFIRM = "confirm"
    RESEARCH = "research"
    ANSWER = "answer"


class PolicyInputError(ValueError):
    """The situation is missing a fact or contradicts itself; `field` names it."""

    def __init__(self, field: str, detail: str) -> None:
        super().__init__(f"{field}: {detail}")
        self.field = field


class PolicyBug(RuntimeError):
    """The policy broke its own promise: no rule fired, or a pass beyond the limit pass."""


class CarFacts(BaseModel):
    """What code knows about one car of the case before deciding (catalogue lookup and cache freshness)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    identity_known: bool  # make and model are known
    in_catalog: bool
    ambiguous: bool  # more than one catalogue variant fits
    plausible_generations: int  # generations that fit condition/year (0 = unknown)
    data_fresh: bool  # every area the current criteria need is cached and fresh
    gearbox_mixed: bool  # accepted values of several gearboxes for one variant (spec 004 FR-028)

    @classmethod
    def of(cls, key: str, state: CarState) -> CarFacts:
        """The facts of car `key` from its assessed state."""
        return cls(key=key, **state.model_dump())


class Situation(BaseModel):
    """Everything the policy may look at in one pass of a turn. `cars` holds the facts of the case's cars;
    `pass_no` counts the policy passes of this turn from 1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: CaseFile
    request: RequestKind
    cars: tuple[CarFacts, ...]
    cost_estimate_eur: Decimal | None = Field(ge=0)  # the research estimate in euros, to the cent
    last_fingerprint: str | None
    cost_approved: bool
    research_declined: bool  # declined by the person or already done this turn (spec 015 PL5 splits the two)
    case_changed: bool
    feasibility_pending: bool
    pass_no: int = Field(ge=1)

    def car(self, key: str) -> CarFacts:
        """The facts of car `key`; raises `PolicyInputError` when the case has a car the facts do not cover."""
        for f in self.cars:
            if f.key == key:
                return f
        raise PolicyInputError("cars", f"no facts for car {key!r}")


class RuleOutcome(BaseModel):
    """One rule's answer in one pass: fired with an action, or skipped; `why` says which branch decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    fired: bool
    why: str
    action: Action | None = None


class Decision(BaseModel):
    """The policy's result for one pass: the action, the rule that decided it and every rule asked up to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Action
    decided_by: str
    trail: tuple[RuleOutcome, ...]


class Rule(Protocol):
    """A rule of the policy: a stable `name` (records and tests refer to it), its `stage`, the requirement it
    implements, and `check`, which never raises for a valid situation."""

    name: ClassVar[str]
    stage: ClassVar[Stage]
    requirement: ClassVar[str | None]

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome: ...


def fire(rule: Rule, action: Action) -> RuleOutcome:
    """The rule decides: `action`, explained by its reason."""
    return RuleOutcome(rule=rule.name, fired=True, why=action.reason, action=action)


def skip(rule: Rule, why: str) -> RuleOutcome:
    """The rule does not apply, and why."""
    return RuleOutcome(rule=rule.name, fired=False, why=why)
