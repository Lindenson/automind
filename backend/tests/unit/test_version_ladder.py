"""Spec 008 US1/US2/US5: the identification ladder over sourced versions (domain/ladder.py)."""

from __future__ import annotations

from automind.domain import ladder
from automind.domain.identity import parse_engine
from automind.domain.ladder import Version, Wanted

OCTAVIA = [  # Skoda Octavia NX on sale (source order: base first)
    Version("1.0 TSI 115 CV", "petrol", 999, 85, ("manual",), ("FWD",), 2020, None),
    Version("1.5 TSI 150 CV", "petrol", 1498, 110, ("manual",), ("FWD",), 2020, None),
    Version("1.5 eTSI 150 CV", "mhev", 1498, 110, ("dct",), ("FWD",), 2020, None),
    Version("2.0 TDI 116 CV", "diesel", 1968, 85, ("manual", "dct"), ("FWD",), 2020, None),
    Version("2.0 TDI 150 CV", "diesel", 1968, 110, ("dct",), ("FWD", "AWD"), 2020, None),
    Version("RS 2.0 TDI 200 CV", "diesel", 1968, 147, ("dct",), ("FWD", "AWD"), 2020, None),
]
A4_B9 = [
    Version("2.0 TFSI 150 CV", "petrol", 1984, 110, ("dct",), ("FWD",), 2015, 2024),
    Version("2.0 TFSI 204 CV", "mhev", 1984, 150, ("dct",), ("FWD", "AWD"), 2015, 2024),
    Version("2.0 TDI 136 CV", "diesel", 1968, 100, ("dct",), ("FWD",), 2015, 2024),
    Version("2.0 TDI 163 CV", "diesel", 1968, 120, ("dct",), ("FWD",), 2015, 2024),
    Version("2.0 TDI 204 CV", "mhev", 1968, 150, ("dct",), ("AWD",), 2019, 2024),
]
GOLF_7 = [
    Version("1.0 TSI 110 CV", "petrol", 999, 81, ("manual", "dct"), ("FWD",), 2017, 2020),
    Version("1.5 TSI 130 CV", "petrol", 1498, 96, ("manual",), ("FWD",), 2017, 2020),
    Version("1.5 TSI 150 CV", "petrol", 1498, 110, ("manual", "dct"), ("FWD",), 2017, 2020),
    Version("2.0 TDI 150 CV", "diesel", 1968, 110, ("manual", "dct"), ("FWD",), 2017, 2020),
]


def said(text: str, **kw: object) -> Wanted:
    return ladder.wanted_of(parse_engine(text), words=text, **kw)  # type: ignore[arg-type]


def step(versions: list[Version], w: Wanted) -> ladder.Step:
    return ladder.next_step(ladder.narrow(versions, w), w)


def test_octavia_two_litre_diesel_asks_the_power_never_one_catalog_row() -> None:
    s = step(OCTAVIA, said("Skoda Octavia 2.0 дизель"))
    assert s.kind == "POWER"
    assert [o.label for o in s.options] == ["2.0 TDI 116 CV", "2.0 TDI 150 CV"]  # the RS only when named


def test_the_rs_line_only_when_named() -> None:
    s = step(OCTAVIA, said("Octavia RS diesel"))
    assert s.kind == "DRIVE"
    assert all("RS" in (o.engine or "") for o in s.options)


def test_one_engine_with_two_drives_asks_only_the_drive() -> None:
    s = step(OCTAVIA, said("Octavia 2.0 TDI 150 CV"))
    assert s.kind == "DRIVE"
    assert [o.drive for o in s.options] == ["FWD", "AWD"]


def test_one_engine_with_two_gearboxes_asks_the_gearbox() -> None:
    s = step(OCTAVIA, said("Octavia 2.0 TDI 116 CV"))
    assert s.kind == "GEARBOX"
    assert [o.gearbox for o in s.options] == ["manual", "dct"]


def test_everything_stated_settles_without_a_question() -> None:
    s = step(GOLF_7, said("Golf 1.5 TSI 150 CV", gearbox="dct", year=2017))
    assert s.kind == "DONE" and s.version is not None and s.version.engine == "1.5 TSI 150 CV"
    assert s.gearbox == "dct" and s.drive == "FWD"


def test_automatic_said_settles_an_engine_with_a_dsg() -> None:
    s = step(GOLF_7, said("Golf 1.5 TSI 150 CV", gearbox="automatic"))
    assert s.kind == "DONE" and s.gearbox == "dct"


def test_a_tapped_option_moves_to_the_next_level_only() -> None:
    w = said("Octavia 2.0 diesel")
    s = step(OCTAVIA, w)
    w = ladder.apply_option(w, s.options[1])  # 150 CV
    s2 = step(OCTAVIA, w)
    assert s2.kind == "DRIVE"


def test_many_engines_fuel_first_then_family_then_power() -> None:
    many = [
        Version(f"1.{i} TSI {100 + 10 * i} CV", "petrol", 1000 + 100 * i, 70 + 7 * i, ("manual",), ("FWD",))
        for i in range(5)
    ]
    many += [Version(f"1.5 TSI {150 + 10 * i} CV", "petrol", 1498, 110 + 8 * i, ("dct",), ("FWD",)) for i in range(3)]
    many += [
        Version("2.0 TDI 116 CV", "diesel", 1968, 85, ("manual",), ("FWD",)),
        Version("2.0 TDI 150 CV", "diesel", 1968, 110, ("dct",), ("FWD",)),
    ]
    w = said("Some car")
    s = step(many, w)
    assert s.kind == "FUEL" and [o.fuel for o in s.options] == ["petrol", "diesel"]
    w = ladder.apply_option(w, s.options[0])
    s = step(many, w)
    assert s.kind == "FAMILY"
    w = ladder.apply_option(w, next(o for o in s.options if o.label == "1.5 TSI"))
    s = step(many, w)
    assert s.kind in ("POWER", "ENGINE") and all("1.5 TSI" in o.label for o in s.options)


def test_electric_has_no_gearbox_question() -> None:
    m3 = [
        Version("RWD 245 CV", "bev", None, 180, ("single",), ("RWD",)),
        Version("Long Range AWD 498 CV", "bev", None, 366, ("single",), ("AWD",)),
    ]
    s = step(m3, said("Tesla Model 3"))
    assert s.kind == "ENGINE"
    w = ladder.apply_option(said("Tesla Model 3"), s.options[0])
    assert step(m3, w).kind == "DONE"


# --- US2: what does not exist is said, the question moves up ------------------------------------------------------


def test_a4_2023_two_point_five_is_missing_and_only_2023_engines_offered() -> None:
    w = said("Audi A4 2.5", year=2023)
    found = ladder.narrow(A4_B9, w)
    assert found.missing == ["2.5"]
    s = ladder.next_step(found, w)
    assert s.kind == "ENGINE"
    assert {o.label for o in s.options} == {v.engine for v in A4_B9}


def test_a_power_that_does_not_exist_is_missing_the_family_kept() -> None:
    w = said("Octavia 2.0 TDI 190 CV")
    found = ladder.narrow(OCTAVIA, w)
    assert found.missing == ["190 CV"]
    s = ladder.next_step(found, w)
    assert s.kind == "POWER" and [o.power_kw for o in s.options] == [85, 110]


# --- US3: decide (choose for me, ask limit) -------------------------------------------------------------------------


def test_choose_for_me_descends_to_one_version_by_the_base_rule() -> None:
    d = ladder.decide(OCTAVIA, said("Octavia 2.0 diesel"), {}, chosen=True)
    assert d.done and d.step.version is not None and d.step.version.engine == "2.0 TDI 116 CV"
    assert d.step.gearbox == "manual"
    assert {a.origin for a in d.auto} == {"CHOSEN"}


def test_a_level_asked_twice_is_settled_by_the_rule() -> None:
    d = ladder.decide(OCTAVIA, said("Octavia 2.0 diesel"), {"POWER": 2})
    assert d.step.kind == "GEARBOX"  # power settled at 116 CV, the next level is asked
    assert [(a.level, a.origin) for a in d.auto] == [("POWER", "LIMIT")]


# --- US5: status line and corrections -------------------------------------------------------------------------------


WORDS = {"diesel": "diésel", "power": "potencia", "gearbox": "caja"}


def test_status_line() -> None:
    w = said("2.0 diesel")
    line = ladder.status_line("Audi A4", "B9", 2023, False, w, "power", WORDS)
    assert line == "Audi A4 · B9 (2023) · diésel 2.0 · potencia: ?"
    assert "~2023" in ladder.status_line("Audi A4", None, 2023, True, w, None, WORDS)


def test_correction_reopens_lower_levels_the_hub_filled() -> None:
    before = {"FUEL": "diesel", "ENGINE": "2.0", "POWER": "110", "GEARBOX": "dct", "DRIVE": "FWD"}
    now = {**before, "FUEL": "petrol"}
    r = ladder.reconcile(before, now, {"GEARBOX": "CHOSEN", "DRIVE": "LIMIT", "POWER": "CHOSEN"}, {})
    assert r.clear == ["POWER", "GEARBOX", "DRIVE"]
    r2 = ladder.reconcile(before, {**before, "DRIVE": "AWD"}, {"GEARBOX": "CHOSEN"}, {})
    assert r2.clear == []  # a level above the change is kept


def test_newer_generation_wins_over_an_older_year() -> None:
    spans = {"b5": (1994, 2001), "b9": (2015, 2024)}
    r = ladder.reconcile({"YEAR": "2023"}, {"YEAR": "2023", "GENERATION": "b5"}, {}, spans)
    assert r.drop == "YEAR" and r.note == {"old": "2023", "new": "B5", "span": "1994–2001"}
    r = ladder.reconcile({"YEAR": "2023", "GENERATION": "b5"}, {"YEAR": "1999", "GENERATION": "b5"}, {}, spans)
    assert r.drop is None
    r = ladder.reconcile({"YEAR": "1999", "GENERATION": "b5"}, {"YEAR": "2023", "GENERATION": "b5"}, {}, spans)
    assert r.drop == "GENERATION"


def test_versions_round_trip_json() -> None:
    v = OCTAVIA[4]
    assert ladder.version_of_json(ladder.version_to_json(v)) == v
