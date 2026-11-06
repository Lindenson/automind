"""The contracts of the dialog's action policy: what is known before a decision (`Situation`), a rule, and a policy.

A rule looks at the situation and returns an `Action` when it applies, else None; the policy asks its rules in order
and the first answer wins. One implementation today (`chain.RulesInOrder`); the `Policy` protocol is the seam for a
later "the model proposes, code gates" planner (spec 012 clarification, owner 2026-11-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, CarState, RequestKind

MAX_QUESTIONS = 3
MAX_HOPS = 8  # spec 007 FR-027: policy passes in one turn before the turn ends with what it has
DEFAULT_CONFIRM_THRESHOLD_EUR = 0.30
DEFAULT_HARD_CAP_EUR = 1.00


@dataclass(frozen=True)
class Situation:
    """Everything the policy may look at in one pass of a turn."""

    case: CaseFile
    request: RequestKind
    cars: dict[str, CarState]
    cost_estimate_eur: float | None
    last_fingerprint: str | None
    cost_approved: bool = False
    research_declined: bool = False
    case_changed: bool = True
    feasibility_pending: bool = False
    confirm_threshold_eur: float = DEFAULT_CONFIRM_THRESHOLD_EUR
    hard_cap_eur: float = DEFAULT_HARD_CAP_EUR
    intake_limits: intake.Limits | None = None
    hops: int = 0
    max_hops: int = MAX_HOPS
    state: dict[str, CarState] = field(init=False)

    def __post_init__(self) -> None:
        # every car of the case has a state (an unknown car: nothing known yet)
        object.__setattr__(self, "state", {c.key: self.cars.get(c.key, CarState()) for c in self.case.cars})


class Rule(Protocol):
    def __call__(self, s: Situation) -> Action | None: ...


class Policy(Protocol):
    def decide(self, s: Situation) -> Action: ...
