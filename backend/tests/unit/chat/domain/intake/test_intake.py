"""Intake loop (spec 005 R5, R6, R11): identity key, progress, next step without repeats, distances."""

from automind.chat.domain.case.casefile import CaseCar, CaseFile, Constraints, EngineHint, IdentifyOutcome
from automind.chat.domain.intake import intake

LIMITS = intake.Limits(max_attempts_per_item=2, max_attempts_per_car=4, full_intake=True)


def _car(**kw: object) -> CaseCar:
    return CaseCar(key="car#1", request_text="byd", **kw)  # type: ignore[arg-type]


def test_identity_key_changes_with_engine_gearbox_year_condition_trim() -> None:
    base = _car(make="SEAT", model="Ateca")
    k = intake.identity_key(base)
    for change in (
        {"constraints": Constraints(engine_hint=EngineHint(displacement_l=1.5))},
        {"constraints": Constraints(gearbox_hint="automatic")},
        {"year": 2025},
        {"condition": "USED"},
        {"constraints": Constraints(trim_hint="FR")},
    ):
        assert intake.identity_key(base.model_copy(update=change)) != k, change
    assert intake.identity_key(base.model_copy(update={"variant_id": "x", "label": "y"})) == k


def test_parse_distance() -> None:
    assert intake.parse_distance("нужно 1-2 тыс км в месяц") == (12000, 24000)
    assert intake.parse_distance("1–2k km a month") == (12000, 24000)
    assert intake.parse_distance("20k a year") == (20000, 20000)
    assert intake.parse_distance("2 000 km al mes") == (24000, 24000)
    assert intake.parse_distance("около 15000 км в год") == (15000, 15000)
    assert intake.parse_distance("Ateca 1.5") is None
    assert intake.parse_distance("2019, 80 тыс км") is None  # a mileage of a used car, not a yearly distance


def test_progress() -> None:
    a = _car(make="BYD", model="Seal U")
    assert intake.progress(a, a, "NOT_FOUND", "CHOICES")
    assert intake.progress(a, a, "CHOICES", "IDENTIFIED")
    assert not intake.progress(a, a, "NOT_FOUND", "NOT_FOUND")
    b = a.model_copy(update={"year": 2025})
    assert intake.progress(a, b, "NOT_FOUND", "NOT_FOUND")


def _unknown_case(attempts: int) -> CaseFile:
    car = _car(make="BYD", model="Seal U", identify=IdentifyOutcome(outcome="NOT_FOUND", need="MODEL"))
    case = CaseFile(cars=[car])
    case.intake.attempts = {"car#1": {"MODEL": attempts}}
    return case


def test_next_step_asks_then_proposes_then_offers_removal() -> None:
    s = intake.next_step(_unknown_case(0), LIMITS)
    assert s.kind == "ASK" and s.items[0].item == "MODEL" and not s.items[0].rephrase
    s = intake.next_step(_unknown_case(1), LIMITS)
    assert s.kind == "ASK" and s.items[0].rephrase  # asked before: different words, never the same text
    s = intake.next_step(_unknown_case(2), LIMITS)
    assert s.kind == "PROPOSE"
    case = _unknown_case(2)
    case.intake.attempts["car#1"]["CHOICE"] = 2
    s = intake.next_step(case, LIMITS)
    assert s.kind == "REMOVE_OR_CHOOSE"


def test_never_the_same_question_hash_twice() -> None:
    case = _unknown_case(0)
    s = intake.next_step(case, LIMITS)
    text = "Какую модель BYD вы имеете в виду?"
    case = intake.record_asked(case, [(s.items[0], text)])
    assert intake.is_repeat(case, s.items[0].car_key, s.items[0].item, text)
    assert not intake.is_repeat(case, s.items[0].car_key, s.items[0].item, text + " (2)")


def test_card_when_every_car_identified() -> None:
    car = _car(make="SEAT", model="Ateca", condition="NEW", variant_id="v1", label="SEAT Ateca 1.5 TSI",
               identify=IdentifyOutcome(outcome="IDENTIFIED"))  # fmt: skip
    assert intake.next_step(CaseFile(cars=[car]), LIMITS).kind == "CARD"
    confirmed = CaseFile(cars=[car])
    confirmed.intake.card_confirmed = True
    assert intake.next_step(confirmed, LIMITS).kind == "NONE"


def test_condition_asked_once_for_all_cars() -> None:
    cars = [
        _car(make="SEAT", model="Ateca", variant_id="v1", identify=IdentifyOutcome(outcome="IDENTIFIED")),
        CaseCar(
            key="car#2",
            request_text="byd",
            make="BYD",
            model="Seal U",
            variant_id="v2",
            identify=IdentifyOutcome(outcome="IDENTIFIED"),
        ),  # fmt: skip
    ]
    s = intake.next_step(CaseFile(cars=cars), LIMITS)
    assert s.kind == "CARD"  # identified cars: new is assumed (shown on the card), not asked on its own
    cars[1] = cars[1].model_copy(update={"identify": IdentifyOutcome(outcome="NEED", need="MODEL")})
    s = intake.next_step(CaseFile(cars=cars), LIMITS)
    assert [i.item for i in s.items] == ["MODEL", "CONDITION"] and s.items[1].car_key is None  # one for every car


def test_condition_and_region_of_text() -> None:
    assert intake.condition_of("Новые") == "NEW" and intake.condition_of("б/у") == "USED"
    assert intake.condition_of("de segunda mano") == "USED" and intake.condition_of("hola") is None
    regions = {"SOUTH": {"names": ["юге испании"], "climate": "HOT"}, "AN": {"names": ["севилья"], "climate": "HOT"},
               "CT": {"names": ["barcelona"], "climate": "MILD"}}  # fmt: skip
    assert intake.region_of("для эксплуатации на юге испании", regions) == ("SOUTH", "HOT", "юге испании")
    assert intake.region_of("живу в Barcelona", regions)[:2] == ("CT", "MILD")  # type: ignore[index]
    assert intake.region_of("для семьи", regions) is None


def test_at_most_three_questions() -> None:
    cars = [CaseCar(key=f"car#{i}", request_text="x", identify=IdentifyOutcome(outcome="NEED", need="MAKE"))
            for i in range(1, 4)]  # fmt: skip
    s = intake.next_step(CaseFile(cars=cars), LIMITS)
    assert s.kind == "ASK" and len(s.items) <= 3
