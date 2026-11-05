"""Spec 011 T060: the six physics checks of research R8 and the choice of the outlier. Pure."""

from __future__ import annotations

import pytest

from automind.acquisition.domain.physics import Facts, Point, check_all, fit_envelope, outlier
from automind.infrastructure.config import physics_config

CFG = {
    **physics_config()["checks"],
    "power_mass_accel": {
        "slack": 0.15,
        "envelope": {"default": [[6.0, 3.0, 6.0], [10.0, 5.5, 9.5], [99.0, 8.0, 16.0]]},  # kg/kW upto -> [min_s, max_s]
    },
}


def names(f: Facts) -> set[str]:
    return {i.check for i in check_all(f, CFG)}


@pytest.mark.parametrize(
    ("ok", "bad"),
    [
        # 1. power-mass-acceleration: 1500 kg / 100 kW = 15 kg/kW -> 8..16 s
        (
            Facts({"max_power": 100, "curb_mass": 1500, "claimed_0_100": 10.5}),
            Facts({"max_power": 100, "curb_mass": 1500, "claimed_0_100": 4.0}),
        ),
        # 2. torque vs power (petrol rpm 7500: 150 kW needs >= 191 N·m)
        (
            Facts({"max_power": 150, "max_torque": 300}, fuel="petrol"),
            Facts({"max_power": 150, "max_torque": 150}, fuel="petrol"),
        ),
        # 3. BEV battery vs range: 77 kWh / 500 km = 154 Wh/km; stated 16 kWh/100 km
        (
            Facts({"battery_kwh": 77, "range_wltp": 500, "consumption_ev": 16.0}, fuel="bev"),
            Facts({"battery_kwh": 77, "range_wltp": 900}, fuel="bev"),
        ),
        # 4. CO2 vs consumption: 5.5 l/100 km petrol -> 131 g/km
        (
            Facts({"co2_wltp": 131, "consumption": 5.5}, fuel="petrol"),
            Facts({"co2_wltp": 160, "consumption": 5.5}, fuel="petrol"),
        ),
        # 5. displacement vs bore × stroke × cylinders (82.5 × 92.8 × 4 = 1984 cm³)
        (
            Facts({"displacement": 1984, "bore": 82.5, "stroke": 92.8, "cylinders": 4}),
            Facts({"displacement": 1598, "bore": 82.5, "stroke": 92.8, "cylinders": 4}),
        ),
        # 6. top speed vs power: 60 kW cannot reach 300 km/h
        (
            Facts({"max_power": 60, "top_speed": 170}, body="hatchback"),
            Facts({"max_power": 60, "top_speed": 300}, body="hatchback"),
        ),
    ],
)
def test_each_check_consistent_and_inconsistent(ok: Facts, bad: Facts) -> None:
    assert check_all(ok, CFG) == []
    assert len(check_all(bad, CFG)) == 1


def test_hybrid_engine_only_torque_is_the_outlier() -> None:
    # the 2026-11-05 case: 225 kW system power with the 250 N·m of the engine alone
    f = Facts({"max_power": 225, "max_torque": 250}, fuel="hybrid", powertrain="HEV")
    (inc,) = check_all(f, CFG)
    assert inc.check == "torque_power" and inc.expected[0] == pytest.approx(225 * 9549 / 7500, rel=1e-6)
    assert outlier(f, CFG).attribute == "max_torque"


def test_bev_skips_torque_and_co2() -> None:
    assert names(Facts({"max_power": 300, "max_torque": 100, "co2_wltp": 50, "consumption": 1}, fuel="bev")) == set()


def test_outlier_by_removal() -> None:
    # a wrong power (40 kW instead of 140) breaks top speed and acceleration; only removing it fixes both
    f = Facts({"max_power": 40, "max_torque": 400, "top_speed": 250, "curb_mass": 1500, "claimed_0_100": 6.0},
              fuel="diesel", body="sedan")  # fmt: skip
    assert names(f) == {"top_speed_power", "power_mass_accel"}
    o = outlier(f, CFG)
    assert o.attribute == "max_power" and o.rule == "removal"


def test_outlier_by_fewest_families_then_tie() -> None:
    base = {"co2_wltp": 160, "consumption": 5.5}
    o = outlier(Facts(base, fuel="petrol", families={"co2_wltp": 1, "consumption": 3}), CFG)
    assert o.attribute == "co2_wltp" and o.rule == "families"
    o = outlier(Facts(base, fuel="petrol", families={"co2_wltp": 3, "consumption": 1}), CFG)
    assert o.attribute == "consumption"
    tie = outlier(Facts(base, fuel="petrol", families={"co2_wltp": 2, "consumption": 2}), CFG)
    assert tie.attribute is None and len(tie.inconsistencies) == 1


def test_missing_inputs_skip_the_check() -> None:
    assert check_all(Facts({"max_power": 150}, fuel="petrol"), CFG) == []
    assert check_all(Facts({"displacement": 1984, "bore": 82.5, "cylinders": 4}), CFG) == []
    assert check_all(Facts({"max_power": 100, "curb_mass": 1500, "claimed_0_100": 4.0}), {**CFG,
                     "power_mass_accel": {"slack": 0.15, "envelope": {}}}) == []  # fmt: skip  # no envelope yet
    assert outlier(Facts({}), CFG).attribute is None


def test_fit_envelope_quantiles_per_bucket() -> None:
    pts = [Point("ICE|FWD", 12.0 + i * 0.2, 9.0 + i * 0.3) for i in range(10)] + [Point("BEV", 5.0, 4.0)]
    env = fit_envelope(pts, min_points=3)
    assert "BEV" not in env  # one point is not an envelope
    (row,) = env["ICE|FWD"]
    assert row[0] == 15.0 and 9.0 <= row[1] < row[2] <= 11.7
    assert env["default"] and all(len(r) == 3 for r in env["default"])
