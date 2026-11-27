"""The dialog's action policy (research R5, spec 015 D2): the rules asked in a fixed order, the first that fires
decides. The model never chooses the action.

Order (`RULES`, by stage):
  limits   — the pass limit, the report after a timeout, a panel edit (spec 007)
  general  — candidates for a need and a budget, else a general answer
  intake   — the intake step about the cars' identity, then the other essential questions (≤ 3)
  confirm  — the intake card, then variants to confirm
  research — confirm the cost at or above the threshold, else research
  answer   — answer from context, feasibility first, or the report (always fires, last)
"""

from __future__ import annotations

from typing import Final

from automind.chat.dialog.policy.contracts import Decision, PolicyBug, Rule, RuleOutcome, Situation
from automind.chat.dialog.policy.rules import answer, confirm, general, intake, limits, research
from automind.chat.domain.decision import PolicyConfig

RULES: Final[tuple[Rule, ...]] = (
    limits.PassLimit(),
    limits.ReportAfterTimeout(),
    limits.PanelEdit(),
    general.Candidates(),
    general.GeneralAnswer(),
    intake.IntakeStep(),
    intake.MissingEssentials(),
    confirm.IntakeCard(),
    confirm.Variants(),
    research.StaleData(),
    answer.AnswerOrReport(),
)


def decide(s: Situation, cfg: PolicyConfig) -> Decision:
    """The decision of one pass: the action of the first rule that fires, with every rule asked up to it.

    Pure. Raises `PolicyBug` for a pass beyond the limit pass (`max_passes + 1`) or when no rule fires (the last
    rule always does); `PolicyInputError` when the situation lacks the facts of a case car. An exception inside a
    rule is never caught."""
    if s.pass_no > cfg.max_passes + 1:
        raise PolicyBug(f"pass {s.pass_no} is beyond the limit pass {cfg.max_passes + 1}")
    trail: list[RuleOutcome] = []
    for rule in RULES:
        outcome = rule.check(s, cfg)
        trail.append(outcome)
        if outcome.action is not None:
            return Decision(action=outcome.action, decided_by=rule.name, trail=tuple(trail))
    raise PolicyBug("no rule fired: the last rule must always fire")
