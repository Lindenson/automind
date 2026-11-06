"""5–6. The data is in place: answer from context, say the request does not fit, or write the report — never the
same report twice."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import Situation
from automind.chat.domain.decision import Action
from automind.chat.domain.fingerprint import fingerprint


def answer_or_report(s: Situation) -> Action:
    case, request = s.case, s.request
    single = len(case.cars) == 1
    # 4b. "find the missing data and update the report": after the research, always a fresh report
    if request == "research_more":
        return Action(kind="REPORT", profile=single, reason="the user asked to research more and update the report")
    # 4c. critique never gets only an apology (spec 004 FR-021): the gaps were researched above, or the report
    # is reworked with what the user disliked
    if request == "critique":
        return Action(kind="REPORT", profile=single, reason="critique: rework the report")
    # 5. answer from context (a correction that changes nothing is answered, not re-reported)
    if request == "correction" and not s.case_changed:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="correction matches the case"
        )
    # 5b. the request does not fit the user's budget or needs: say so before any report (spec 003 FR-020)
    if s.feasibility_pending and request not in ("weights_change",):
        return Action(kind="FEASIBILITY", reason="a constraint is not met or could not be checked")
    if request in ("weights_change", "follow_up_question"):
        return Action(kind="ANSWER_FROM_CONTEXT", profile=single, reason="follow-up answered from validated data")
    # 6. report, never repeated unchanged
    if s.last_fingerprint is not None and fingerprint(case) == s.last_fingerprint:
        return Action(
            kind="ANSWER_FROM_CONTEXT", nothing_new=True, profile=single, reason="case unchanged since last report"
        )
    return Action(kind="REPORT", profile=single, reason="case changed")
