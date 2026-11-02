"""Case file: deterministic application of typed deltas (FR-002, FR-003, FR-007, FR-009; R3, R4)."""

import pytest
from pydantic import ValidationError

from automind.domain.casefile import (
    CarContext,
    CarRef,
    CaseDelta,
    CaseFile,
    PersonaChange,
    PriorityChange,
    apply,
    set_weights,
)

YEAR = 2026


def case_with_two_cars() -> CaseFile:
    c, _ = apply(
        CaseFile(),
        CaseDelta(
            add_cars=[
                CarRef(request_text="brand-new Dacia Bigster", make="Dacia", model="Bigster", condition="NEW"),
                CarRef(
                    request_text="used Land Cruiser Prado", make="Toyota", model="Land Cruiser Prado", condition="USED"
                ),
            ]
        ),
        current_year=YEAR,
    )
    return c


def test_add_cars_assigns_stable_keys_and_logs():
    c, log = apply(
        CaseFile(),
        CaseDelta(add_cars=[CarRef(request_text="Golf GTI", make="Volkswagen", model="Golf")]),
        current_year=YEAR,
    )
    assert [x.key for x in c.cars] == ["car#1"]
    assert log == ["car#1 added: Golf GTI"]
    c2, _ = apply(c, CaseDelta(remove_cars=["car#1"]), current_year=YEAR)
    c3, _ = apply(c2, CaseDelta(add_cars=[CarRef(request_text="i30 N")]), current_year=YEAR)
    assert [x.key for x in c3.cars] == ["car#2"]  # keys are never reused


def test_apply_is_pure():
    c = case_with_two_cars()
    before = c.model_dump()
    apply(c, CaseDelta(set_persona=PersonaChange(persona="BUYER", source="INFERRED")), current_year=YEAR)
    assert c.model_dump() == before


def test_latest_statement_wins_and_is_logged():
    c, _ = apply(CaseFile(), CaseDelta(set_budget={"max_eur": 30000}), current_year=YEAR)
    c, log = apply(c, CaseDelta(set_budget={"max_eur": 40000}), current_year=YEAR)
    assert c.budget.max_eur == 40000
    assert log == ["budget: ≤ €30,000 → ≤ €40,000"]
    c, log = apply(c, CaseDelta(set_persona=PersonaChange(persona="BUYER", source="INFERRED")), current_year=YEAR)
    assert log == ["persona: UNKNOWN → BUYER"]


def test_replace_car_keeps_key_resets_resolution_keeps_others():
    c = case_with_two_cars()
    c.cars[1].variant_id = "v-250"
    c.cars[1].resolution = "CONFIRMED"
    c, _ = apply(c, CaseDelta(set_persona=PersonaChange(persona="BUYER", source="INFERRED")), current_year=YEAR)
    new, log = apply(
        c,
        CaseDelta(
            replace_cars=[
                CarContext(
                    target_key="car#2",
                    request_text="used ~10 years old LC Prado 150",
                    make="Toyota",
                    model="Land Cruiser Prado",
                    condition="USED",
                    age_years=10,
                    constraints={"generation_hint": "150"},
                )
            ]
        ),
        current_year=YEAR,
    )
    car = new.cars[1]
    assert car.key == "car#2"
    assert car.variant_id is None and car.resolution == "UNRESOLVED" and car.alternatives == []
    assert car.constraints.generation_hint == "150"
    assert new.cars[0].request_text == "brand-new Dacia Bigster"  # the other car is untouched
    assert new.persona == "BUYER"
    assert log == ["car#2 replaced: used Land Cruiser Prado → used ~10 years old LC Prado 150 (USED, ~2016)"]


def test_replace_with_identical_request_is_a_no_op():
    c, _ = apply(
        case_with_two_cars(),
        CaseDelta(
            replace_cars=[
                CarContext(
                    target_key="car#2",
                    request_text="Prado 150",
                    make="Toyota",
                    model="Land Cruiser Prado",
                    condition="USED",
                    age_years=10,
                    constraints={"generation_hint": "150"},
                )
            ]
        ),
        current_year=YEAR,
    )
    c.cars[1].variant_id, c.cars[1].resolution = "v-150", "CONFIRMED"
    again, log = apply(
        c,
        CaseDelta(
            replace_cars=[
                CarContext(
                    target_key="car#2",
                    request_text="the used 150, not new",
                    make="Toyota",
                    model="Land Cruiser Prado",
                    condition="USED",
                    age_years=10,
                    constraints={"generation_hint": "150"},
                )
            ]
        ),
        current_year=YEAR,
    )
    assert log == []
    assert again.cars[1].variant_id == "v-150" and again.cars[1].resolution == "CONFIRMED"


def test_unknown_target_key_is_rejected():
    with pytest.raises(ValueError, match="car#9"):
        apply(case_with_two_cars(), CaseDelta(remove_cars=["car#9"]), current_year=YEAR)


def test_more_than_three_cars_is_recorded_and_flagged():
    c = case_with_two_cars()
    c, _ = apply(
        c, CaseDelta(add_cars=[CarRef(request_text="BMW X5"), CarRef(request_text="Audi Q7")]), current_year=YEAR
    )
    assert len(c.cars) == 4 and c.too_many_cars


@pytest.mark.parametrize(
    ("ctx", "year", "age"),
    [({"age_years": 10}, 2016, 10), ({"year": 2015}, 2015, 11), ({"year": 2015, "age_years": 11}, 2015, 11)],
)
def test_age_and_year_are_consistent(ctx, year, age):
    c, _ = apply(
        case_with_two_cars(), CaseDelta(set_car_context=[CarContext(target_key="car#2", **ctx)]), current_year=YEAR
    )
    car = c.cars[1]
    assert car.year == year and car.age_years == age
    assert abs(car.year - (YEAR - car.age_years)) <= 1


def test_set_car_context_changing_condition_resets_resolution():
    c = case_with_two_cars()
    c.cars[0].variant_id, c.cars[0].resolution = "v1", "AUTO_OK"
    c, log = apply(
        c, CaseDelta(set_car_context=[CarContext(target_key="car#1", condition="USED", year=2019)]), current_year=YEAR
    )
    assert c.cars[0].resolution == "UNRESOLVED" and c.cars[0].condition == "USED"
    assert log == ["car#1: condition NEW → USED, year 2019"]


def test_priorities_add_update_remove():
    c, log = apply(
        CaseFile(), CaseDelta(add_priorities=[PriorityChange(criterion="status", strength="HIGH")]), current_year=YEAR
    )
    assert [(p.criterion, p.strength, p.source) for p in c.priorities] == [("status", "HIGH", "USER")]
    assert log == ["priority added: status (HIGH)"]
    c, log = apply(c, CaseDelta(add_priorities=[PriorityChange(criterion="status", strength="LOW")]), current_year=YEAR)
    assert c.priorities[0].strength == "LOW" and log == ["priority status: HIGH → LOW"]
    c, log = apply(c, CaseDelta(remove_priorities=["status"]), current_year=YEAR)
    assert c.priorities == [] and log == ["priority removed: status"]


def test_unknown_criterion_keys_rejected():
    with pytest.raises(ValidationError):
        PriorityChange(criterion="nice_colour", strength="HIGH")


def test_unmapped_wishes_are_kept_once():
    c, log = apply(CaseFile(), CaseDelta(unmapped_wishes=["nice colour"]), current_year=YEAR)
    c, log2 = apply(c, CaseDelta(unmapped_wishes=["nice colour"]), current_year=YEAR)
    assert c.unmapped_wishes == ["nice colour"] and log == ["not assessable: nice colour"] and log2 == []


def test_weights_are_normalized_to_100():
    c = set_weights(CaseFile(), {"reliability": 3, "ownership_cost": 1, "status": 0})
    assert c.weights == {"reliability": 75.0, "ownership_cost": 25.0, "status": 0.0}
    assert abs(sum(c.weights.values()) - 100) <= 0.01
    assert c.weights_overridden
    with pytest.raises(ValueError):
        set_weights(CaseFile(), {"reliability": -1, "status": 2})
    with pytest.raises(ValueError):
        set_weights(CaseFile(), {"reliability": 0})
    with pytest.raises(ValueError):
        set_weights(CaseFile(), {"nice_colour": 1})


def test_profile_usage_depth_mileage_rates_race():
    c, log = apply(
        case_with_two_cars(),
        CaseDelta(
            set_profile={"age": 20},
            set_usage=["CITY", "MOUNTAINS"],
            set_depth="DEEP",
            set_annual_km=20000,
            set_rates_override={"fuel_eur_per_l": 1.7},
            set_race_settings={"surface": "WET", "extra_load_kg": 150},
            set_prediction={"winner_key": "car#1"},
        ),
        current_year=YEAR,
    )
    assert c.profile.age == 20 and c.usage == ["CITY", "MOUNTAINS"] and c.depth == "DEEP" and c.annual_km == 20000
    assert c.rates_override.fuel_eur_per_l == 1.7 and c.race_settings.surface == "WET"
    assert c.prediction.winner_key == "car#1"
    assert "age: 20" in log and "usage: CITY, MOUNTAINS" in log and "depth: STANDARD → DEEP" in log
    with pytest.raises(ValueError, match="car#7"):
        apply(c, CaseDelta(set_prediction={"winner_key": "car#7"}), current_year=YEAR)


def test_user_edit_persona_not_overridden_by_weak_inference():
    c, _ = apply(
        CaseFile(), CaseDelta(set_persona=PersonaChange(persona="EXPERT", source="USER_EDIT")), current_year=YEAR
    )
    c2, log = apply(c, CaseDelta(set_persona=PersonaChange(persona="BUYER", source="INFERRED")), current_year=YEAR)
    assert c2.persona == "EXPERT" and log == []
    c3, _ = apply(c, CaseDelta(set_persona=PersonaChange(persona="BUYER", source="ASKED")), current_year=YEAR)
    assert c3.persona == "BUYER"  # an explicit statement is the latest statement and wins


def test_round_trip_json():
    c = case_with_two_cars()
    assert CaseFile.model_validate(c.model_dump(mode="json")) == c


def test_repeating_a_car_does_not_add_it_twice():
    c = case_with_two_cars()
    again, log = apply(
        c,
        CaseDelta(add_cars=[CarRef(request_text="Dacia Bigster new", make="Dacia", model="Bigster", condition="NEW")]),
        current_year=YEAR,
    )
    assert len(again.cars) == 2 and log == []


def test_restating_the_same_car_with_fewer_details_keeps_its_context():
    """Live G1: "but I meant the used 150, not new" came without the age."""
    c, _ = apply(
        case_with_two_cars(),
        CaseDelta(
            set_car_context=[CarContext(target_key="car#2", age_years=10, constraints={"generation_hint": "150"})]
        ),
        current_year=YEAR,
    )
    c.cars[1].variant_id, c.cars[1].resolution = "v-150", "CONFIRMED"
    again, log = apply(
        c,
        CaseDelta(
            replace_cars=[
                CarContext(
                    target_key="car#2",
                    request_text="the used 150, not new",
                    make="Toyota",
                    model="Land Cruiser Prado",
                    condition="USED",
                    constraints={"generation_hint": "150"},
                )
            ]
        ),
        current_year=YEAR,
    )
    assert log == [] and again.cars[1].resolution == "CONFIRMED" and again.cars[1].year == 2016


def test_replacing_with_another_model_does_not_inherit_age():
    c, _ = apply(
        case_with_two_cars(),
        CaseDelta(set_car_context=[CarContext(target_key="car#2", age_years=10)]),
        current_year=YEAR,
    )
    new, _ = apply(
        c,
        CaseDelta(
            replace_cars=[CarContext(target_key="car#2", request_text="Toyota RAV4", make="Toyota", model="RAV4")]
        ),
        current_year=YEAR,
    )
    assert new.cars[1].year is None and new.cars[1].model == "RAV4"
