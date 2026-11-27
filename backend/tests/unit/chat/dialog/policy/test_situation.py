"""`situation_from` (spec 015 T211, T213): the facts of a pass from the turn state, the estimate rounded half-up to
the cent, and one error per broken invariant beside a situation built as before."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from automind.chat.dialog.policy import situation_from
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.decision import CarState, RequestKind
from automind.shared.contracts.json import JsonObject

FRESH: JsonObject = {"state": CarState(in_catalog=True, data_fresh=True).model_dump()}


@dataclass
class Facts:
    """A `PolicyIn` stand-in: the case at version 3 with car#1 assessed on it."""

    request_kind: RequestKind | None = "compare"
    assessments: dict[str, JsonObject] = field(default_factory=lambda: {"car#1": FRESH})
    assessed_version: int | None = 3
    cost_estimate: float | None = None
    cost_approved: bool | None = None
    research_declined: bool | None = None
    research_done: bool | None = None
    case_changed: bool | None = True
    feasibility_pending: bool | None = None


def _case(*keys: str) -> CaseFile:
    return CaseFile(cars=[CaseCar(key=k, request_text=k) for k in keys or ("car#1",)])


def _read(facts: Facts, case: CaseFile | None = None, version: int = 3):  # noqa: ANN202
    return situation_from(facts, case=case or _case(), case_version=version, last_fingerprint="fp", pass_no=2)


def test_the_facts_of_a_consistent_pass() -> None:
    read = _read(Facts(research_done=True, feasibility_pending=True))
    s = read.situation
    assert read.errors == ()
    assert s.car("car#1").data_fresh and s.pass_no == 2 and s.last_fingerprint == "fp"
    assert s.research_declined and s.feasibility_pending and s.request == "compare"


@pytest.mark.parametrize(("estimate", "eur"), [(None, None), (0.304, "0.30"), (0.305, "0.31"), (1.0, "1.00")])
def test_the_estimate_is_rounded_half_up_to_the_cent(estimate: float | None, eur: str | None) -> None:
    s = _read(Facts(cost_estimate=estimate)).situation
    assert s.cost_estimate_eur == (None if eur is None else Decimal(eur))


def test_a_case_car_without_an_assessment_is_an_error_and_gets_empty_facts() -> None:
    read = _read(Facts(), _case("car#1", "car#2"))
    assert [e.field for e in read.errors] == ["cars"] and "car#2" in str(read.errors[0])
    assert read.situation.car("car#2") == read.situation.car("car#2").of("car#2", CarState())


def test_an_assessment_of_a_car_the_case_does_not_have_is_an_error() -> None:
    read = _read(Facts(assessments={"car#1": FRESH, "car#9": FRESH}))
    assert [e.field for e in read.errors] == ["cars"] and "car#9" in str(read.errors[0])
    assert [f.key for f in read.situation.cars] == ["car#1"]


@pytest.mark.parametrize("assessed", [None, 2])
def test_cars_assessed_on_another_case_version_are_an_error(assessed: int | None) -> None:
    read = _read(Facts(assessed_version=assessed))
    assert [e.field for e in read.errors] == ["assessed_version"]
