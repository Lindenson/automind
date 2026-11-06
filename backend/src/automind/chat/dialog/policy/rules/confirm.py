"""3. What the person confirms before research: the intake card (cars, profile, research cost; spec 005 R7), then
any variant that is ambiguous, used or new to the catalogue."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import Situation
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import Action, CarState


def intake_card(s: Situation) -> Action | None:
    """The confirmation card (spec 005 R7): when a proposed version waits for the user, or research is about to start
    after an intake with questions or above the cost threshold. Simple unambiguous cached comparisons skip it."""
    case, est = s.case, s.cost_estimate_eur
    if case.intake.card_confirmed or not case.cars or not any(c.identify is not None for c in case.cars):
        return None
    if not all(c.variant_id for c in case.cars):
        return None
    proposed = any(c.resolution == "PROPOSED" for c in case.cars)
    stale = any(not s.state[c.key].data_fresh for c in case.cars)
    asked = bool(case.intake.last_questions)
    chosen_by_us = bool(case.candidates)  # spec 007 US7: candidates the user did not name are always confirmed
    if (
        proposed
        or chosen_by_us
        or (stale and not s.research_declined and (asked or (est or 0.0) >= s.confirm_threshold_eur))
    ):
        return Action(kind="CONFIRM_INTAKE", cars=[c.key for c in case.cars], over_cap=(est or 0.0) > s.hard_cap_eur,
                      reason="confirm the cars, the profile and the research")  # fmt: skip
    return None


def variants(s: Situation) -> Action | None:
    """Variants to confirm: ambiguous, used or new to the catalogue."""
    to_confirm = [c.key for c in s.case.cars if needs_confirmation(s.case, c.key, s.state[c.key])]
    if to_confirm:
        return Action(kind="CONFIRM_VARIANTS", cars=to_confirm, reason="ambiguous, used or new-to-catalog variant")
    return None


def needs_confirmation(case: CaseFile, key: str, st: CarState) -> bool:
    car = case.car(key)
    if car.resolution in ("CONFIRMED", "AUTO_OK"):
        return False
    if car.resolution == "UNKNOWN_MODEL":
        return False  # asked as a question, never proposed
    if car.resolution == "PROPOSED":
        return True  # a proposed variant (catalog or resolver) is confirmed by the user, never silently (spec 005)
    return st.ambiguous or car.condition == "USED" or not st.in_catalog
