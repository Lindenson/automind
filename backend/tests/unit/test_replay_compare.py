"""Replay comparison and report (spec 011 T014, research R4, contracts/replay-cli.md)."""

import pytest

from automind.acquisition.domain.replay import Gold, PageResult, Value, compare, report, wilson_lb

TOL = {"max_power": ("rel", 0.02), "curb_mass": ("rel", 0.03), "displacement": ("abs", 10.0)}


def gold(variant: str, attribute: str, num=None, text=None, tol=None, kind=None) -> Gold:  # noqa: ANN001
    return Gold(variant, attribute, num, text, "kW", tol, kind, "exact", "eea_co2_2024")


def val(attribute: str, num=None, text=None, url="https://www.km77.com/a", variant="v1", sid="s1") -> Value:  # noqa: ANN001
    return Value(sid, url, variant, attribute, num, text, None, f"{attribute} {num or text}")


GOLD = {
    ("v1", "max_power"): gold("v1", "max_power", 140.0),
    ("v1", "curb_mass"): gold("v1", "curb_mass", 1465.0),
    ("v1", "displacement"): gold("v1", "displacement", 1995.0),
    ("v1", "drivetrain"): gold("v1", "drivetrain", text="Trasera"),
}


def test_compare_counts_covered_and_match_with_abs_and_rel_tolerance():
    values = [
        val("max_power", 141.0),  # within 2 %
        val("curb_mass", 1540.0),  # 5 % off -> mismatch
        val("displacement", 2004.0),  # within 10 cm3
        val("top_speed", 235.0),  # no gold: not covered
    ]
    c = compare(values, GOLD, TOL)
    assert c.by_attribute == {
        "max_power": {"covered": 1, "match": 1},
        "curb_mass": {"covered": 1, "match": 0},
        "displacement": {"covered": 1, "match": 1},
    }
    assert [m.attribute for m in c.mismatches] == ["curb_mass"]
    assert c.mismatches[0].ours == 1540.0 and c.mismatches[0].gold == 1465.0
    assert c.mismatches[0].gold_rule == "exact" and c.mismatches[0].gold_dataset == "eea_co2_2024"


def test_gold_tolerance_wins_over_the_default():
    g = {("v1", "max_power"): gold("v1", "max_power", 140.0, tol=5.0, kind="abs")}
    assert compare([val("max_power", 144.0)], g, TOL).by_attribute["max_power"]["match"] == 1


def test_text_attributes_compare_normalised():
    c = compare([val("drivetrain", text="  trasera ")], GOLD, TOL)
    assert c.by_attribute["drivetrain"] == {"covered": 1, "match": 1}
    c = compare([val("drivetrain", text="Tracción delantera")], GOLD, TOL)
    assert c.by_attribute["drivetrain"]["match"] == 0


def test_report_metrics_and_mismatch_order():
    pages = [
        PageResult(
            "s1", "https://www.km77.com/b", ("v1",), 10, [val("curb_mass", 1540.0, url="https://www.km77.com/b")]
        ),
        PageResult(
            "s2",
            "https://www.km77.com/a",
            ("v1",),
            8,
            [val("max_power", 150.0, sid="s2"), val("curb_mass", 1600.0, sid="s2")],
        ),  # fmt: skip
        PageResult("s3", "https://www.km77.com/c", ("v1",), 0, []),
    ]
    r = report("km77@v1", pages, GOLD, TOL, period=("2026-10-06", "2026-11-05"))
    assert r["version"] == "km77@v1" and r["period"] == {"from": "2026-10-06", "to": "2026-11-05"}
    assert r["pages"] == 3 and r["pages_with_fields"] == 2
    assert r["rows_read"] == 18 and r["rows_accepted"] == 3
    assert r["fields_per_page"] == pytest.approx(6.0) and r["yield"] == pytest.approx(1.0)
    assert r["pass_rate"] == pytest.approx(3 / 18)
    assert r["gold_covered"] == 3 and r["gold_match"] == 0 and r["accuracy"] == 0.0
    assert r["accuracy_lb"] == pytest.approx(wilson_lb(0, 3))
    assert [(m["attribute"], m["url"]) for m in r["mismatches"]] == [
        ("curb_mass", "https://www.km77.com/a"),
        ("curb_mass", "https://www.km77.com/b"),
        ("max_power", "https://www.km77.com/a"),
    ]
    assert set(r["mismatches"][0]) >= {"snapshot_id", "url", "variant_id", "attribute", "ours", "gold", "unit",
                                       "gold_rule", "gold_dataset", "quote"}  # fmt: skip


def test_report_with_empty_gold():
    r = report("km77@v1", [PageResult("s1", "u", ("v1",), 5, [val("max_power", 140.0)])], {}, TOL)
    assert r["gold_covered"] == 0 and r["accuracy"] is None and r["accuracy_lb"] is None
    assert r["mismatches"] == []


def test_wilson_lower_bound():
    assert wilson_lb(0, 0) is None
    assert 0.86 < wilson_lb(48, 50) < 0.87
    assert wilson_lb(50, 50) < 1.0


def test_reader_accuracy_is_scored_on_every_row_read():
    """A reader that puts a wrong number under a label is wrong even when the checks reject the value."""
    accepted = [val("max_power", 140.0)]
    read = [val("max_power", 140.0), val("curb_mass", None, text="400 Nm")]
    r = report("km77@test", [PageResult("s1", "u", ("v1",), 2, accepted, scored=read)], GOLD, TOL)
    assert r["rows_accepted"] == 1 and r["gold_covered"] == 2 and r["gold_match"] == 1
    assert r["mismatches"][0]["attribute"] == "curb_mass" and r["mismatches"][0]["ours"] == "400 Nm"
