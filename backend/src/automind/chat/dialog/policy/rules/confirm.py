"""Stage CONFIRM: what the person confirms before research — the intake card (cars, profile, research cost; spec 005
R7), then any variant that is ambiguous, used or new to the catalogue."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from automind.chat.dialog.policy.contracts import CarFacts, RuleOutcome, Situation, Stage, fire, skip
from automind.chat.domain.case import CaseCar
from automind.chat.domain.decision import Action, PolicyConfig


class IntakeCard:
    """The confirmation card: when a proposed version waits for the person, the cars were chosen by us, or research
    is about to start after an intake with questions or above the cost threshold. Simple unambiguous cached
    comparisons skip it."""

    name: ClassVar[str] = "intake_card"
    stage: ClassVar[Stage] = Stage.CONFIRM
    requirement: ClassVar[str | None] = "spec 005 R7; spec 007 US7"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        case, est = s.case, s.cost_estimate_eur or Decimal(0)
        if case.intake.card_confirmed:
            return skip(self, "the card is confirmed")
        if not any(c.identify is not None for c in case.cars):
            return skip(self, "no car went through identification")
        if not all(c.variant_id for c in case.cars):
            return skip(self, "a car has no version yet")
        proposed = any(c.resolution == "PROPOSED" for c in case.cars)
        chosen_by_us = bool(case.candidates)  # spec 007 US7: candidates the person did not name are confirmed
        stale = any(not s.car(c.key).data_fresh for c in case.cars)
        asked = bool(case.intake.last_questions)
        research_ahead = stale and not s.research_declined and (asked or est >= cfg.confirm_threshold_eur)
        if not (proposed or chosen_by_us or research_ahead):
            return skip(self, "nothing to confirm: no proposal, no candidates, no research ahead")
        return fire(self, Action.confirm_intake([c.key for c in case.cars], over_cap=est > cfg.hard_cap_eur,
                                                reason="confirm the cars, the profile and the research"))  # fmt: skip


class Variants:
    """Variants to confirm: proposed, ambiguous, used or new to the catalogue."""

    name: ClassVar[str] = "variants"
    stage: ClassVar[Stage] = Stage.CONFIRM
    requirement: ClassVar[str | None] = "spec 005"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        to_confirm = [c.key for c in s.case.cars if needs_confirmation(c, s.car(c.key))]
        if not to_confirm:
            return skip(self, "every version is settled")
        return fire(self, Action.confirm_variants(to_confirm, "ambiguous, used or new-to-catalog variant"))


def needs_confirmation(car: CaseCar, facts: CarFacts) -> bool:
    """A version the person confirms: proposed, or not settled and ambiguous, used or new to the catalogue."""
    if car.resolution in ("CONFIRMED", "AUTO_OK"):
        return False
    if car.resolution == "UNKNOWN_MODEL":
        return False  # asked as a question, never proposed
    if car.resolution == "PROPOSED":
        return True  # a proposed variant (catalog or resolver) is confirmed by the person, never silently (spec 005)
    return facts.ambiguous or car.condition == "USED" or not facts.in_catalog
