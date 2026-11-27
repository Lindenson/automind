"""A feasibility finding waits for the person (spec 003 FR-020, moved into the service by spec 015 T212) until they
acknowledge these very checks or the constraints as they stand ("look at used")."""

from __future__ import annotations

from automind.chat.application.services.feasibility.feasibility import needs_ack, pending
from automind.chat.domain.case import Budget, CaseFile

CHECKS = {"results": [], "fingerprint": "fp-1"}


def test_no_checks_or_checks_without_a_fingerprint_wait_for_nothing() -> None:
    assert pending(CaseFile(), None) is False
    assert pending(CaseFile(), {"results": []}) is False


def test_checks_wait_until_acknowledged() -> None:
    assert pending(CaseFile(), CHECKS) is True
    assert pending(CaseFile(feasibility_ack="fp-1"), CHECKS) is False


def test_an_acknowledgement_of_the_constraints_covers_later_checks_until_they_change() -> None:
    case = CaseFile(budget=Budget(max_eur=20000, intent="USED"))
    case.feasibility_ack = needs_ack(case)
    assert pending(case, CHECKS) is False
    case.budget = Budget(max_eur=15000, intent="USED")
    assert pending(case, CHECKS) is True
