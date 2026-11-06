"""4. Data stale or missing for the current criteria: confirm the cost when the estimate reaches the threshold,
else research."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import Situation
from automind.chat.domain.decision import Action


def stale_data(s: Situation) -> Action | None:
    stale = [c.key for c in s.case.cars if not s.state[c.key].data_fresh]
    if not stale or s.research_declined:
        return None
    est = s.cost_estimate_eur or 0.0
    if est >= s.confirm_threshold_eur and not s.cost_approved:
        return Action(kind="CONFIRM_COST", cars=stale, over_cap=est > s.hard_cap_eur, reason=f"estimated €{est:.2f}")
    return Action(kind="RESEARCH", cars=stale, reason="data stale or missing for the current criteria")
