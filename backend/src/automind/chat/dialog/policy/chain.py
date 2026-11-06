"""The dialog's action policy (research R5): rules asked in a fixed order, the first that applies decides. The
LLM never chooses the action.

Order (one list, `RULES`):
  limits  — hop limit, report after a timeout, panel edit (spec 007)
  general — candidates for a need and a budget, else a general answer
  intake  — the intake step about the cars' identity, then the other essential questions (≤ 3)
  confirm — the intake card, then variants to confirm
  research — confirm the cost above the threshold, else research
  answer  — (when no rule applies) answer from context, feasibility first, or the report — never repeated unchanged
"""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import (
    DEFAULT_CONFIRM_THRESHOLD_EUR,
    DEFAULT_HARD_CAP_EUR,
    MAX_HOPS,
    Rule,
    Situation,
)
from automind.chat.dialog.policy.rules import answer, confirm, general, intake, limits, research
from automind.chat.domain import intake as intake_domain
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, CarState, RequestKind

RULES: tuple[Rule, ...] = (
    limits.hop_limit,
    limits.report_after_timeout,
    limits.panel_edit,
    general.candidates,
    general.general_answer,
    intake.intake_step,
    intake.missing_essentials,
    confirm.intake_card,
    confirm.variants,
    research.stale_data,
)


class RulesInOrder:
    """The policy: the first rule that applies decides; otherwise answer or report."""

    def decide(self, s: Situation) -> Action:
        for rule in RULES:
            if (action := rule(s)) is not None:
                return action
        return answer.answer_or_report(s)


def decide(
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
    confirm_threshold_eur: float = DEFAULT_CONFIRM_THRESHOLD_EUR,
    hard_cap_eur: float = DEFAULT_HARD_CAP_EUR,
    intake_limits: intake_domain.Limits | None = None,
    hops: int = 0,
    max_hops: int = MAX_HOPS,
) -> Action:
    """The decision of one pass, for callers that hold the facts as arguments."""
    return RulesInOrder().decide(Situation(
        case=case, request=request, cars=cars, cost_estimate_eur=cost_estimate_eur, last_fingerprint=last_fingerprint,
        cost_approved=cost_approved, research_declined=research_declined, case_changed=case_changed,
        feasibility_pending=feasibility_pending, confirm_threshold_eur=confirm_threshold_eur, hard_cap_eur=hard_cap_eur,
        intake_limits=intake_limits, hops=hops, max_hops=max_hops,
    ))  # fmt: skip
