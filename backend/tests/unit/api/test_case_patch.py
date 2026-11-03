"""Case panel edits (FR-009): PATCH semantics are pure and validated."""

import pytest
from pydantic import ValidationError

from automind.api.rest import CasePatch, apply_patch
from automind.domain.casefile import CaseDelta, CaseFile, PriorityChange, apply


def test_patch_persona_is_a_user_edit_and_logged():
    new, changes = apply_patch(CaseFile(), CasePatch(persona="BUYER", annual_km=20000), current_year=2026)
    assert new.persona == "BUYER" and new.persona_source == "USER_EDIT" and new.annual_km == 20000
    assert changes == ["persona: UNKNOWN → BUYER", "annual mileage: 15,000 → 20,000 km"]


def test_patch_weights_normalized_and_priority_removed():
    case, _ = apply(CaseFile(), CaseDelta(add_priorities=[PriorityChange(criterion="status")]), current_year=2026)
    new, changes = apply_patch(
        case, CasePatch(weights={"status": 40, "reliability": 60}, remove_priority="status"), current_year=2026
    )
    assert new.weights == {"status": 40.0, "reliability": 60.0} and new.weights_overridden
    assert new.priorities == [] and "priority removed: status" in changes


def test_patch_rejects_unknown_fields_and_bad_weights():
    with pytest.raises(ValidationError):
        CasePatch(colour="red")
    with pytest.raises(ValueError):
        apply_patch(CaseFile(), CasePatch(weights={"nice_colour": 1}), current_year=2026)


def test_patch_rates_can_be_cleared_back_to_default():
    a, _ = apply_patch(CaseFile(), CasePatch(rates_override={"fuel_eur_per_l": 1.7}), current_year=2026)
    assert a.rates_override.fuel_eur_per_l == 1.7
    b, changes = apply_patch(a, CasePatch(rates_override={"fuel_eur_per_l": None}), current_year=2026)
    assert b.rates_override.fuel_eur_per_l is None and changes == ["rates: defaults"]


def test_patch_constraints_partial_and_clear():
    from automind.api.rest import CasePatch, apply_patch
    from automind.domain.casefile import Budget, CaseFile

    c = CaseFile(budget=Budget(max_eur=25000, intent="USED"))
    new, ch = apply_patch(c, CasePatch.model_validate({"budget": {"intent": "NEW"}}), current_year=2026)
    assert new.budget.max_eur == 25000 and new.budget.intent == "NEW" and ch
    new, _ = apply_patch(new, CasePatch.model_validate({"budget": {"max_eur": None}}), current_year=2026)
    assert new.budget.max_eur is None
    new, _ = apply_patch(new, CasePatch.model_validate({"running_cost_limit": {"amount_eur": 200},
                                                        "needs": {"passengers": 5}}), current_year=2026)  # fmt: skip
    assert new.running_cost_limit.per_month == 200 and new.needs.passengers == 5
    new, _ = apply_patch(new, CasePatch.model_validate({"clear_running_cost_limit": True}), current_year=2026)
    assert new.running_cost_limit is None
