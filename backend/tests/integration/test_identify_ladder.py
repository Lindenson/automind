"""Spec 008: identification over the sourced versions of a generation (chat 9b5c0b0c replayed on the ladder).
"New Skoda Octavia 2.0 diesel" asks the power (116/150), never takes one catalog row; "used Audi A4 2.5, 2023"
says there is no 2.5 and offers only the 2023 engines; "choose for me" settles; the ask limit settles."""

from types import SimpleNamespace

from automind.application import identify
from automind.domain import intake
from automind.domain.casefile import CaseCar, CaseFile, Constraints, Pending
from automind.domain.identity import parse_engine
from automind.domain.ladder import Generation, Version
from automind.infrastructure.config import reference
from automind.orchestration import phrases
from automind.orchestration.prompts import load_all

OCTAVIA = [
    Version("1.5 TSI 115 CV", "petrol", 1498, 85, ("manual",), ("FWD",), 2020, None, "https://km77.es/o", "115 CV"),
    Version("2.0 TDI 116 CV", "diesel", 1968, 85, ("manual", "dct"), ("FWD",), 2020, None, "https://km77.es/o"),
    Version("2.0 TDI 150 CV", "diesel", 1968, 110, ("dct",), ("FWD", "AWD"), 2020, None, "https://km77.es/o"),
    Version("RS 2.0 TDI 200 CV", "diesel", 1968, 147, ("dct",), ("AWD",), 2020, None, "https://km77.es/o"),
]
A4 = [
    Version("2.0 TFSI 150 CV", "petrol", 1984, 110, ("dct",), ("FWD",), 2015, 2024, "https://km77.es/a"),
    Version("2.0 TDI 136 CV", "diesel", 1968, 100, ("dct",), ("FWD",), 2015, 2024, "https://km77.es/a"),
    Version("2.0 TDI 163 CV", "diesel", 1968, 120, ("dct",), ("FWD",), 2015, 2024, "https://km77.es/a"),
    Version("2.0 TDI 204 CV", "mhev", 1968, 150, ("dct",), ("AWD",), 2019, 2024, "https://km77.es/a"),
]


class Store:
    def __init__(self) -> None:
        self.gens = {
            ("Skoda", "Octavia", "Mk4"): Generation("Skoda", "Octavia", "Mk4", 2020, None, "WAGON", OCTAVIA),
            ("Audi", "A4", "B9"): Generation("Audi", "A4", "B9", 2015, 2024, "SEDAN", A4),
        }
        self.asked: list[tuple[object, ...]] = []

    async def get(self, make, model, generation, year, new, ttl_days):  # noqa: ANN001, ANN201
        self.asked.append((make, model, generation, year, new))
        return self.gens.get((make, model, generation))

    async def put(self, g):  # noqa: ANN001, ANN201
        raise AssertionError("no look-up expected")


def _ports() -> SimpleNamespace:
    return SimpleNamespace(ref=reference(load_all()), versions=Store())


def _octavia() -> CaseCar:
    return CaseCar(
        key="car#2",
        request_text="Skoda Octavia 2025 2.0 l diesel",
        make="Skoda",
        model="Octavia",
        condition="NEW",
        year=2025,
        constraints=Constraints(engine_hint=parse_engine("2.0 diesel")),
    )


def _audi() -> CaseCar:
    return CaseCar(
        key="car#1",
        request_text="audi A4 2.5 l second hand with 50000 km",
        make="Audi",
        model="A4",
        condition="USED",
        year=2023,
        age_years=3,
        mileage_km=50000,
        constraints=Constraints(engine_hint=parse_engine("2.5 l")),
    )


def _pick(case: CaseFile, text: str):  # noqa: ANN202
    return intake.pick(
        case,
        text,
        gearbox_words=phrases.GEARBOX_WORDS,
        yes=phrases.yes_or_no(text) == "yes",
        choose=phrases.choose_for_me(text) or phrases.go_ahead(text),
    )


def _ask(case: CaseFile, car: CaseCar) -> CaseFile:
    o = car.identify
    assert o is not None
    case.pending = Pending(
        kind="QUESTIONS",
        items=[
            {"kind": o.need, "car": car.key, "item": o.need, "choices": [c.model_dump(mode="json") for c in o.choices]}
        ],
    )
    case.intake.bump(car.key, str(o.need))
    return case


async def test_octavia_two_litre_diesel_asks_the_power_then_the_gearbox() -> None:
    ports, car = _ports(), _octavia()
    case = CaseFile(cars=[car])
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.outcome == "CHOICES" and o.need == "POWER"
    assert [c.label for c in o.choices] == ["2.0 TDI 116 CV", "2.0 TDI 150 CV"]
    assert car.variant_id is None  # never one catalog row
    case = _ask(case, car)
    case, _ = _pick(case, "2.0 TDI 116 CV")
    car = case.car("car#2")
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.need == "GEARBOX" and [c.gearbox for c in o.choices] == ["manual", "dct"]


async def test_octavia_choose_for_me_settles_the_base_version() -> None:
    ports, car = _ports(), _octavia()
    case = CaseFile(cars=[car])
    await identify._ladder(ports, case, car, 2026)
    case, log = _pick(_ask(case, car), "выбери сам")
    car = case.car("car#2")
    assert car.chosen_for_me
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.outcome == "IDENTIFIED"
    assert car.variant_id and car.resolution == "CONFIRMED" and "116" in (car.label or "")
    assert car.ladder is not None and car.ladder.origin.get("POWER") == "CHOSEN" and car.ladder.certainty == "SOURCED"


async def test_audi_2023_two_point_five_does_not_exist_only_b9_engines() -> None:
    ports, car = _ports(), _audi()
    case = CaseFile(cars=[car])
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.outcome == "CHOICES" and o.missing == ["2.5"]
    assert {c.label for c in o.choices} == {v.engine for v in A4}  # B9 only, built in 2023
    assert ports.versions.asked[0][2] == "B9"


async def test_a_level_asked_twice_is_settled_by_the_rule_with_a_note() -> None:
    ports, car = _ports(), _octavia()
    case = CaseFile(cars=[car])
    await identify._ladder(ports, case, car, 2026)
    case.intake.attempts["car#2"] = {"POWER": 2}
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.need == "GEARBOX"  # power settled at the base 116 CV, the gearbox is asked
    assert {"kind": "settled_by_rule", "label": "2.0 TDI 116 CV"} in o.events
    assert car.ladder is not None and car.ladder.origin.get("POWER") == "LIMIT"


async def test_correcting_the_fuel_reopens_the_levels_below() -> None:
    ports, car = _ports(), _octavia()
    case = CaseFile(cars=[car])
    car.chosen_for_me = True
    await identify._ladder(ports, case, car, 2026)
    assert car.variant_id is not None
    car.variant_id, car.chosen_for_me, car.identify = None, False, None  # what a correction does (casefile)
    car.constraints.engine_hint = parse_engine("gasolina")
    o = await identify._ladder(ports, case, car, 2026)
    assert o is not None and o.outcome == "IDENTIFIED" and "1.5 TSI" in (car.label or "")  # one petrol version
    assert car.constraints.gearbox_hint is None  # the manual "choose for me" took for the diesel is open again
    assert car.ladder is not None and "ENGINE" not in car.ladder.origin
