"""Stage ANSWER: the data is in place — answer from context, say the request does not fit, or write the report; never
the same report twice. The last rule: it always fires."""

from __future__ import annotations

from typing import ClassVar

from automind.chat.dialog.policy.contracts import RuleOutcome, Situation, Stage, fire
from automind.chat.domain.decision import Action, PolicyConfig, RequestKind
from automind.chat.domain.fingerprint import fingerprint

FOLLOW_UPS: frozenset[RequestKind] = frozenset({"weights_change", "follow_up_question"})


class AnswerOrReport:
    """The fallback of the chain, in order: "find more" and a critique get a fresh report; a correction that
    changed nothing is answered; an unmet constraint is said first; a follow-up is answered from the data; the report
    is written unless the case is as at the last report. Spec 013 T041 splits it into goal rules."""

    name: ClassVar[str] = "answer_or_report"
    stage: ClassVar[Stage] = Stage.ANSWER
    requirement: ClassVar[str | None] = "research R5 rules 5–6; spec 004 FR-021; spec 003 FR-020"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        return fire(self, self._action(s))

    @staticmethod
    def _action(s: Situation) -> Action:
        request, profile = s.request, len(s.case.cars) == 1
        if request == "research_more":  # after the research, always a fresh report
            return Action.report("the user asked to research more and update the report", profile=profile)
        if request == "critique":  # never only an apology: the gaps were researched, or the report is reworked
            return Action.report("critique: rework the report", profile=profile)
        if request == "correction" and not s.case_changed:  # a correction that changes nothing is answered
            return Action.answer_from_context("correction matches the case", nothing_new=True, profile=profile)
        if s.feasibility_pending and request != "weights_change":  # said before any report (spec 003 FR-020)
            return Action.feasibility("a constraint is not met or could not be checked")
        if request in FOLLOW_UPS:
            return Action.answer_from_context("follow-up answered from validated data", profile=profile)
        if s.last_fingerprint is not None and fingerprint(s.case) == s.last_fingerprint:
            return Action.answer_from_context("case unchanged since last report", nothing_new=True, profile=profile)
        return Action.report("case changed", profile=profile)
