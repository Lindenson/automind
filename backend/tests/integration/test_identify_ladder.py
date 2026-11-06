"""Spec 008: identification over the sourced versions of a generation (chat 9b5c0b0c replayed on the ladder).
"New Skoda Octavia 2.0 diesel" asks the power (116/150), never takes one catalog row; "used Audi A4 2.5, 2023"
says there is no 2.5 and offers only the 2023 engines; "choose for me" settles; the ask limit settles."""

from types import SimpleNamespace

from automind.chat.application.services.identification import identify
from automind.chat.dialog import phrases
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.case.casefile import CaseCar, CaseFile, Constraints, Pending
from automind.chat.domain.identification.ladder import Generation, Version
from automind.chat.domain.intake import intake
from automind.delivery.bootstrap import reference
from automind.shared.vehicle.identity import parse_engine

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

# 009 FR-023: the sources give the first engines no end year; the facelift's engines start later. Test-only makes:
# the settled versions are stored in the catalog, and a real "Toyota Land Cruiser Prado" row would change the goldens
PRADO = [
    Version("3.0 D-4D 173 CV", "diesel", 2982, 127, ("manual", "automatic"), ("AWD",), 2009, None, "https://km77.es/p"),
    Version("4.0 V6 282 CV", "petrol", 3956, 207, ("automatic",), ("AWD",), 2009, 2013, "https://km77.es/p"),
    Version("2.8 D-4D 177 CV", "diesel", 2755, 130, ("manual", "automatic"), ("AWD",), 2015, None, "https://km77.es/p"),
]
# chat 5821ac77: the 2024 facelift sells the PHEV at 288 CV; the 2020 page writes "265 CV, 2020–"
SORENTO = [
    Version(
        "1.6 T-GDi HEV 230 CV", "hybrid", 1598, 169, ("automatic",), ("FWD", "AWD"), 2020, None, "https://km77.es/s"
    ),
    Version("1.6 T-GDi PHEV 265 CV", "phev", 1598, 195, ("automatic",), ("AWD",), 2020, None, "https://km77.es/s"),
    Version("2.2 CRDi 193 CV", "diesel", 2151, 142, ("dct",), ("FWD", "AWD"), 2020, None, "https://km77.es/s"),
    Version(
        "1.6 T-GDi HEV 215 CV", "hybrid", 1598, 158, ("automatic",), ("FWD", "AWD"), 2024, None, "https://km77.es/s"
    ),
    Version("1.6 T-GDi PHEV 288 CV", "phev", 1598, 212, ("automatic",), ("AWD",), 2024, None, "https://km77.es/s"),
]


class Store:
    def __init__(self) -> None:
        self.gens = {
            ("Skoda", "Octavia", "Mk4"): Generation("Skoda", "Octavia", "Mk4", 2020, None, "WAGON", OCTAVIA),
            ("Audi", "A4", "B9"): Generation("Audi", "A4", "B9", 2015, 2024, "SEDAN", A4),
            ("Laddertoyota", "Land Cruiser Prado", "J150"): Generation(
                "Laddertoyota", "Land Cruiser Prado", "J150", 2009, 2023, "SUV", PRADO
            ),  # fmt: skip
            ("Ladderkia", "Sorento", "MQ4"): Generation("Ladderkia", "Sorento", "MQ4", 2020, None, "SUV", SORENTO),
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


async def _catalog_rows(make: str) -> None:
    from automind.chat.application.services.identification import resolve
    from automind.shared.infrastructure import db

    await db.init_db()
    for name, kw in (("2.0 TDI 115 CV Selection", 85), ("2.0 TDI 150 CV DSG Style", 110)):
        ident = resolve.VariantIdentity(make=make, model="Octavia", generation="Mk4", variant_name=name,
                                        powertrain="ICE", body_class="WAGON", generation_years_from=2020,
                                        generation_years_to=None, engine_cc=1968, power_kw=kw, fuel="diesel",
                                        certainty="exact")  # fmt: skip
        await resolve.upsert_variant(ident, reference({}))


async def test_fallback_without_a_sourced_list_asks_the_power_never_takes_the_first_row() -> None:
    """FR-020 (decided 2026-11-04): with no sourced list the catalog rows follow the same levels; "2.0 diesel"
    with a 115 and a 150 CV row is asked, never silently the 115 CV row (chat 9b5c0b0c)."""
    make = "Fallbackskoda"
    await _catalog_rows(make)
    ports = SimpleNamespace(ref=reference(load_all()), versions=None)
    car = _octavia()
    car.make, car.request_text = make, f"{make} Octavia 2.0 diesel"
    case = CaseFile(cars=[car])
    o = await identify._fallback(ports, case, car, 2026, None)
    assert o.outcome == "CHOICES" and o.need == "POWER", o
    assert {c.power_kw for c in o.choices} == {85, 110}
    assert car.variant_id is None
    assert car.ladder is not None and car.ladder.certainty == "LESS_CERTAIN"
    case, _ = _pick(_ask(case, car), "выбери сам")
    car = case.car("car#2")
    o = await identify._fallback(ports, case, car, 2026, None)
    assert o.outcome == "IDENTIFIED" and "115" in (car.label or "")
    assert car.ladder is not None and car.ladder.origin.get("POWER") == "CHOSEN"
    assert {"kind": "identity_less_certain"} in o.events


def _prado(age: int) -> CaseCar:
    return CaseCar(key="car#1", request_text=f"ленд круер прадо 150 возрастом {age} лет", make="Laddertoyota",
                   model="Land Cruiser Prado", condition="USED", year=2026 - age, age_years=age,
                   constraints=Constraints(generation_hint="J150"))  # fmt: skip


async def test_used_prado_15_years_offers_only_the_engines_sold_in_its_year() -> None:
    """009 FR-023 (chat 20b5b7f9): the first identification of a 15-year-old Prado offers the 2011 engines only."""
    ports, car = _ports(), _prado(15)
    o = await identify._ladder(ports, CaseFile(cars=[car]), car, 2026)
    assert o is not None and o.outcome == "CHOICES"
    assert {c.label for c in o.choices} == {"3.0 D-4D 173 CV", "4.0 V6 282 CV"}


async def test_used_prado_after_the_facelift_is_not_offered_the_engine_it_replaced() -> None:
    """The 3.0 D-4D has no end year in the source, but the 2.8 D-4D of the facelift replaced it: an 8-year-old
    Prado (2018) has one engine, and the 3.0 D-4D is neither taken nor offered."""
    ports, car = _ports(), _prado(8)
    car.chosen_for_me = True
    o = await identify._ladder(ports, CaseFile(cars=[car]), car, 2026)
    assert o is not None and o.outcome == "IDENTIFIED", o
    assert "2.8 D-4D 177 CV" in (car.label or "")
    assert car.ladder is not None and not any("3.0" in x for x in car.ladder.others)


async def test_new_sorento_phev_is_the_facelift_288_cv_not_the_2020_265_cv() -> None:
    """Chat 5821ac77: a new Sorento PHEV bought now is the 2024 facelift's 288 CV; the 2020 265 CV is not on sale."""
    ports = _ports()
    car = CaseCar(key="car#1", request_text="Sorento PHEV nuevo", make="Ladderkia", model="Sorento", condition="NEW",
                  constraints=Constraints(generation_hint="MQ4", engine_hint=parse_engine("PHEV")))  # fmt: skip
    car.chosen_for_me = True
    o = await identify._ladder(ports, CaseFile(cars=[car]), car, 2026)
    assert o is not None and o.outcome == "IDENTIFIED", o
    assert "288" in (car.label or "") and "265" not in (car.label or "")
    assert car.ladder is not None and all("230" not in x and "265" not in x for x in car.ladder.others)


async def test_new_sorento_asks_among_the_current_engines_only() -> None:
    ports = _ports()
    car = CaseCar(key="car#1", request_text="Kia Sorento nuevo", make="Ladderkia", model="Sorento", condition="NEW",
                  constraints=Constraints(generation_hint="MQ4"))  # fmt: skip
    o = await identify._ladder(ports, CaseFile(cars=[car]), car, 2026)
    assert o is not None and o.outcome == "CHOICES"
    assert {c.label for c in o.choices} == {"1.6 T-GDi HEV 215 CV", "1.6 T-GDi PHEV 288 CV", "2.2 CRDi 193 CV"}
