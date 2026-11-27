"""Stage RESEARCH: data stale or missing for the current criteria — confirm the cost when the estimate reaches the
threshold, else research."""

from __future__ import annotations

from typing import ClassVar

from automind.chat.dialog.policy.contracts import RuleOutcome, Situation, Stage, fire, skip
from automind.chat.domain.decision import Action, PolicyConfig


class StaleData:
    """Cars whose data is stale or missing: research them, after a cost confirmation at or above the threshold."""

    name: ClassVar[str] = "stale_data"
    stage: ClassVar[Stage] = Stage.RESEARCH
    requirement: ClassVar[str | None] = "research R5 rule 4; FR-041"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        stale = [c.key for c in s.case.cars if not s.car(c.key).data_fresh]
        if not stale:
            return skip(self, "data fresh for every car")
        if s.research_declined:
            return skip(self, "research declined or done this turn")
        est = s.cost_estimate_eur or 0.0
        if est >= cfg.confirm_threshold_eur and not s.cost_approved:
            return fire(
                self, Action.confirm_cost(stale, over_cap=est > cfg.hard_cap_eur, reason=f"estimated €{est:.2f}")
            )
        return fire(self, Action.research(stale, "data stale or missing for the current criteria"))
