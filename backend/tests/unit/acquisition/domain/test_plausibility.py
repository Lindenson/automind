"""Plausibility rules (spec 003 FR-014; research R8): by powertrain and across attributes. Pure."""

import yaml

from automind.acquisition.domain.plausibility import Context, check
from automind.shared.infrastructure.config.loader import config_dir

RULES = yaml.safe_load((config_dir() / "plausibility.yaml").read_text(encoding="utf-8"))
DIESEL = Context(powertrain="ICE", fuel="diesel")


def test_diesel_saloon_0_100_in_1_9_s_is_rejected():
    r = check("claimed_0_100", 1.9, DIESEL, RULES)
    assert not r.ok and r.rule_id == "claimed_0_100.ICE_DIESEL"


def test_normal_values_pass():
    assert check("claimed_0_100", 7.5, DIESEL, RULES).ok
    assert check("measured_0_100", 2.9, Context(powertrain="BEV"), RULES).ok
    assert check("max_power", 140, DIESEL, RULES).ok


def test_power_to_weight_above_one_kw_per_kg_is_rejected():
    ctx = Context(powertrain="ICE", fuel="petrol", known={"curb_mass": 150.0})
    r = check("max_power", 180, ctx, RULES)
    assert not r.ok and r.rule_id == "pw_ratio_max"
    r2 = check("curb_mass", 150, Context(powertrain="ICE", known={"max_power": 180.0}), RULES)
    assert not r2.ok and r2.rule_id == "pw_ratio_max"


def test_sprint_too_quick_for_the_power_to_weight():
    ctx = Context(powertrain="ICE", fuel="petrol", known={"max_power": 66.0, "curb_mass": 1100.0})  # 60 kW/t
    assert check("claimed_0_100", 11.5, ctx, RULES).ok
    weak = Context(powertrain="ICE", fuel="petrol", known={"max_power": 40.0, "curb_mass": 1100.0})  # 36 kW/t
    r = check("claimed_0_100", 6.0, weak, RULES)
    assert not r.ok and r.rule_id == "slow_car_quick_sprint"  # first matching rule wins


def test_measured_far_from_claimed_is_rejected():
    ctx = Context(powertrain="ICE", known={"claimed_0_100": 7.5})
    assert check("measured_0_100", 7.9, ctx, RULES).ok
    r = check("measured_0_100", 3.9, ctx, RULES)
    assert not r.ok and r.rule_id == "measured_vs_claimed"


def test_official_price_range():
    assert check("official_price_es", 58900, DIESEL, RULES).ok
    assert not check("official_price_es", 900, DIESEL, RULES).ok


def test_non_numeric_and_unknown_attributes_pass():
    assert check("drivetrain", "RWD", DIESEL, RULES).ok
    assert check("unknown_attr", 5, DIESEL, RULES).ok
