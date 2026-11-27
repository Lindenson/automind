"""The one situation builder of the policy tests (spec 015 T204): a `Situation` and a `PolicyConfig` from the facts a
test cares about, with today's defaults for the rest; `act` decides with the arguments the old 14-argument `decide`
took, so the regression test feeds the same arguments to both."""

from __future__ import annotations

from automind.chat.dialog.policy import CarFacts, Decision, Situation, decide
from automind.chat.domain import intake
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, CarState, PolicyConfig, RequestKind

THRESHOLD, CAP, MAX_PASSES = 0.30, 1.00, 8


def config(
    *, threshold: float = THRESHOLD, cap: float = CAP, max_passes: int = MAX_PASSES, limits: intake.Limits | None = None
) -> PolicyConfig:
    return PolicyConfig(confirm_threshold_eur=threshold, hard_cap_eur=cap, max_passes=max_passes,
                        intake=limits or intake.Limits(full_intake=False))  # fmt: skip


def facts(case: CaseFile, cars: dict[str, CarState] | None = None) -> tuple[CarFacts, ...]:
    """Facts for every car of the case: the given state, else the state of a car not assessed yet."""
    given = cars or {}
    return tuple(CarFacts.of(c.key, given.get(c.key, CarState())) for c in case.cars)


def situation(
    case: CaseFile,
    request: RequestKind = "compare",
    cars: dict[str, CarState] | None = None,
    *,
    cost_estimate_eur: float | None = None,
    last_fingerprint: str | None = None,
    cost_approved: bool = False,
    research_declined: bool = False,
    case_changed: bool = True,
    feasibility_pending: bool = False,
    pass_no: int = 1,
) -> Situation:
    return Situation(case=case, request=request, cars=facts(case, cars), cost_estimate_eur=cost_estimate_eur,
                     last_fingerprint=last_fingerprint, cost_approved=cost_approved,
                     research_declined=research_declined, case_changed=case_changed,
                     feasibility_pending=feasibility_pending, pass_no=pass_no)  # fmt: skip


def decision(
    case: CaseFile,
    request: RequestKind,
    cars: dict[str, CarState],
    *,
    cost_estimate_eur: float | None,
    last_fingerprint: str | None,
    cost_approved: bool = False,
    research_declined: bool = False,
    case_changed: bool = True,
    feasibility_pending: bool = False,
    confirm_threshold_eur: float = THRESHOLD,
    hard_cap_eur: float = CAP,
    intake_limits: intake.Limits | None = None,
    hops: int = 0,
    max_hops: int = MAX_PASSES,
) -> Decision:
    """The new `decide` over the old call's arguments (`hops` passes done → `pass_no = hops + 1`)."""
    s = situation(case, request, cars, cost_estimate_eur=cost_estimate_eur, last_fingerprint=last_fingerprint,
                  cost_approved=cost_approved, research_declined=research_declined, case_changed=case_changed,
                  feasibility_pending=feasibility_pending, pass_no=hops + 1)  # fmt: skip
    return decide(s, config(threshold=confirm_threshold_eur, cap=hard_cap_eur, max_passes=max_hops,
                            limits=intake_limits))  # fmt: skip


def act(case: CaseFile, request: RequestKind, cars: dict[str, CarState], **kw: object) -> Action:
    """The action of `decision(...)`."""
    return decision(case, request, cars, **kw).action  # type: ignore[arg-type]  # the old call's keywords
