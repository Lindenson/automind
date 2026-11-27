"""The one way to a `Situation` (spec 015 D3, D6): the facts of a policy pass from what the turn state holds, the
case and the last report's fingerprint, checked against the invariants.

`situation_from` is pure. A broken invariant does not raise here: it comes back in `SituationRead.errors` beside a
situation built as before PL2 (a car the facts miss gets the facts of an empty `CarState`), and the policy node
decides what it does — fail the turn (`PolicyConfig.strict_inputs`) or log and count it. The invariants:
- `cars`: facts for exactly the case's cars (no car without its assessment, no assessment of another car);
- `assessed_version`: the cars were assessed on the case version the policy decides on.
A pass beyond the limit pass is not an input error but a `PolicyBug` (`decide`)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from automind.chat.dialog.policy.contracts import CarFacts, PolicyInputError, Situation
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import CarState, RequestKind
from automind.shared.contracts.json import JsonObject

CENT = Decimal("0.01")


class PolicyFacts(Protocol):
    """What the policy reads from the turn state (the policy node's `PolicyIn`)."""

    @property
    def request_kind(self) -> RequestKind | None: ...
    @property
    def assessments(self) -> Mapping[str, JsonObject]: ...
    @property
    def assessed_version(self) -> int | None: ...
    @property
    def cost_estimate(self) -> float | None: ...
    @property
    def cost_approved(self) -> bool | None: ...
    @property
    def research_declined(self) -> bool | None: ...
    @property
    def research_done(self) -> bool | None: ...
    @property
    def case_changed(self) -> bool | None: ...
    @property
    def feasibility_pending(self) -> bool | None: ...


@dataclass(frozen=True)
class SituationRead:
    """The situation of a pass and the invariants it broke (empty: none)."""

    situation: Situation
    errors: tuple[PolicyInputError, ...]


def situation_from(
    inp: PolicyFacts, *, case: CaseFile, case_version: int, last_fingerprint: str | None, pass_no: int
) -> SituationRead:
    """The situation of pass `pass_no` over `case` (at `case_version`); research done this turn counts as declined
    (spec 015 PL5 splits the two). The cost is rounded half-up to the cent."""
    cost = None if inp.cost_estimate is None else Decimal(str(inp.cost_estimate)).quantize(CENT, ROUND_HALF_UP)
    situation = Situation(
        case=case, request=inp.request_kind or "compare", cars=_facts(inp.assessments, case),
        cost_estimate_eur=cost, last_fingerprint=last_fingerprint, cost_approved=bool(inp.cost_approved),
        research_declined=bool(inp.research_declined or inp.research_done), case_changed=bool(inp.case_changed),
        feasibility_pending=bool(inp.feasibility_pending), pass_no=pass_no,
    )  # fmt: skip
    return SituationRead(situation, (*_car_errors(inp.assessments, case), *_version_errors(inp, case_version)))


def _facts(assessments: Mapping[str, JsonObject], case: CaseFile) -> tuple[CarFacts, ...]:
    """The facts of every case car from its assessment; a car not assessed gets an empty `CarState`'s."""
    return tuple(CarFacts.of(car.key, CarState.model_validate(assessments[car.key]["state"])
                             if car.key in assessments else CarState()) for car in case.cars)  # fmt: skip


def _car_errors(assessments: Mapping[str, JsonObject], case: CaseFile) -> list[PolicyInputError]:
    keys = {car.key for car in case.cars}
    missing, foreign = sorted(keys - assessments.keys()), sorted(assessments.keys() - keys)
    errors = [PolicyInputError("cars", f"case cars without an assessment: {missing}")] if missing else []
    if foreign:
        errors.append(PolicyInputError("cars", f"assessments of cars the case does not have: {foreign}"))
    return errors


def _version_errors(inp: PolicyFacts, case_version: int) -> list[PolicyInputError]:
    if inp.assessed_version == case_version:
        return []
    return [PolicyInputError("assessed_version", f"assessed {inp.assessed_version}, the case is at {case_version}")]
