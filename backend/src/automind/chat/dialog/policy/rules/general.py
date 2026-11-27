"""Stage GENERAL: no car to compare yet — candidates when a need and a budget are known, else a general answer."""

from __future__ import annotations

from typing import ClassVar

from automind.chat.dialog.policy.contracts import RuleOutcome, Situation, Stage, fire, skip
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, PolicyConfig, RequestKind

GENERAL_REQUESTS: frozenset[RequestKind] = frozenset({"general_question", "chitchat"})


class Candidates:
    """No car but a need and a budget (or a make to choose from): propose candidates, not a general text."""

    name: ClassVar[str] = "candidates"
    stage: ClassVar[Stage] = Stage.GENERAL
    requirement: ClassVar[str | None] = "spec 007 US7; 009 FR-022"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        if s.request in GENERAL_REQUESTS:
            return skip(self, "a general question or chitchat")
        if not wants_candidates(s.case):
            return skip(self, "a car named, or no need and budget")
        return fire(self, Action.select_candidates("no car named: a need and a budget"))


class GeneralAnswer:
    """A general question, chitchat, or a case without cars: a general answer."""

    name: ClassVar[str] = "general_answer"
    stage: ClassVar[Stage] = Stage.GENERAL
    requirement: ClassVar[str | None] = "research R5 rule 1"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        if s.request not in GENERAL_REQUESTS and s.case.cars:
            return skip(self, "cars to compare")
        return fire(self, Action.answer_general("general question or no cars in the case"))


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
