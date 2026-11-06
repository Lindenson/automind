"""Chat fcf5b3b8: three independent sources that agree beat one manufacturer page (engine-only torque)."""

from automind.shared.evidence import evidence as ev


def c(i: int, v: float, t: str, d: str) -> ev.ClaimIn:
    return ev.ClaimIn(str(i), "max_torque", v, t, d)


def test_three_agreeing_sources_beat_a_single_manufacturer_value():
    s = ev.select_value(
        "max_torque",
        [
            c(1, 265, "MANUFACTURER", "kia.com"),
            c(2, 350, "SPEC_DATABASE", "km77.com"),
            c(3, 350, "INSTRUMENTED_TEST", "autopista.es"),
            c(4, 350, "PUBLICATION", "fastestlaps.com"),
        ],
    )
    assert s.value == 350 and s.resolution_rule == "MAJORITY_OVER_SINGLE" and 265 in s.alternatives


def test_manufacturer_still_wins_against_one_or_two_others():
    s = ev.select_value(
        "max_torque",
        [
            c(1, 265, "MANUFACTURER", "kia.com"),
            c(2, 350, "SPEC_DATABASE", "km77.com"),
            c(3, 350, "PUBLICATION", "x.com"),
        ],
    )
    assert s.value == 265 and s.confidence_rule == "HIGH:MANUFACTURER"
