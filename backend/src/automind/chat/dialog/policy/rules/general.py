"""No car to compare yet: candidates when a need and a budget are known, else a general answer."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import Situation
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action


def candidates(s: Situation) -> Action | None:
    """1. spec 007 US7: no car but a need and a budget → candidates, not a general text."""
    if s.request not in ("general_question", "chitchat") and wants_candidates(s.case):
        return Action(kind="SELECT_CANDIDATES", reason="no car named: a need and a budget")
    return None


def general_answer(s: Situation) -> Action | None:
    """1. A general question, chitchat, or a case without cars."""
    if s.request in ("general_question", "chitchat") or not s.case.cars:
        return Action(kind="ANSWER_GENERAL", reason="general question or no cars in the case")
    return None


def wants_candidates(case: CaseFile) -> bool:
    """No car named, a budget, and a class or a need (a body, a family, passengers, a usage); or a make to choose
    from with no candidate of it proposed yet (009 FR-022: "find me a Kia to replace my Prado")."""
    if case.wanted_make:
        make = case.wanted_make.lower()
        proposed = any(str(x.get("make") or "").lower() == make for x in case.candidates)
        named = any((c.make or "").lower() == make and not c.replaced for c in case.cars)
        if not (proposed or named):
            return True
    if any(not c.replaced for c in case.cars) or not case.budget.max_eur:
        return False
    need = (case.wanted_body is not None or case.profile.family == "FAMILY" or "FAMILY" in case.usage
            or (case.needs.passengers or 0) >= 4)  # fmt: skip
    return need
