"""Owner 2026-11-28 (chat fbdb4c8e): a mild hybrid's starter-generator boost is part of the power the race uses —
the data's when it has one, else the make's typical boost, always written as an assumption."""

from automind.chat.domain.assessment import dragrace


def _car(**kw: object) -> dragrace.CarInput:
    base = {
        "car_id": "c",
        "label": "C 200 d",
        "powertrain": "MHEV",
        "power_kw": 120.0,
        "mass_kg": 1755.0,
        "drivetrain": "RWD",
        "transmission": "automatic",
        "make": "Mercedes-Benz",
    }
    return dragrace.CarInput(**{**base, **kw})  # type: ignore[arg-type]


def _race(*cars: dragrace.CarInput) -> dict[str, dragrace.CarResult]:
    return {r.label: r for r in dragrace.simulate(list(cars), dragrace.RaceSettings()).results}


def test_a_mild_hybrid_is_faster_with_its_boost_and_says_it_was_assumed() -> None:
    res = _race(_car(), _car(label="ICE", powertrain="ICE"))
    mhev, ice = res["C 200 d"], res["ICE"]
    assert mhev.t_0_100 is not None and ice.t_0_100 is not None and mhev.t_0_100 < ice.t_0_100
    boost = [a for a in mhev.assumptions if a["name"] == "mhev_boost"]
    assert boost and boost[0]["value"] == 15.0 and "Mercedes-Benz" in boost[0]["reason"]
    assert not [a for a in ice.assumptions if a["name"] == "mhev_boost"]


def test_the_data_s_boost_is_used_and_not_assumed() -> None:
    (r,) = _race(_car(mhev_boost_kw=17.0)).values()
    assert not [a for a in r.assumptions if a["name"] == "mhev_boost"]


def test_an_unknown_make_takes_the_typical_boost() -> None:
    (r,) = _race(_car(make="Kia")).values()
    assert [a["value"] for a in r.assumptions if a["name"] == "mhev_boost"] == [10.0]
