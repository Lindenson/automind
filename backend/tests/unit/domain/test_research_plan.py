"""Case-driven research planner (FR-013, FR-014, FR-019..FR-021; research R8)."""

from datetime import UTC, datetime, timedelta

import pytest

from automind.shared.research_order.plan import (
    FRESHNESS_DAYS,
    ROUNDS,
    CarToPlan,
    SourceHit,
    areas_for,
    gaps,
    minimum_met,
    plan,
)

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def car(key="car#1", vid="v1", condition="NEW", age=None, es=True):
    return CarToPlan(key=key, variant_id=vid, condition=condition, age_years=age, sold_in_es=es)


def test_areas_by_persona_and_condition():
    assert {"specs", "engineering", "manufacturer"} <= areas_for("EXPERT", [], "NEW")
    assert {"specs", "maintenance", "reliability", "reviews", "price"} <= areas_for("BUYER", [], "NEW")
    assert "used_issues" in areas_for("BUYER", [], "USED")
    assert "used_issues" not in areas_for("BUYER", [], "NEW")
    assert {"specs", "measured"} <= areas_for("PERFORMANCE", [], "NEW")
    assert "engineering" not in areas_for("BUYER", [], "NEW")


def test_areas_follow_criteria():
    a = areas_for("PERFORMANCE", ["status", "comfort"], "NEW")
    assert {"price", "manufacturer", "reviews"} <= a


def test_freshness_defaults():
    assert FRESHNESS_DAYS["specs"] == 365 and FRESHNESS_DAYS["maintenance"] == 365
    assert FRESHNESS_DAYS["reliability"] == 180 and FRESHNESS_DAYS["reviews"] == 180
    assert FRESHNESS_DAYS["price"] == 30 and FRESHNESS_DAYS["manufacturer"] == 30
    assert FRESHNESS_DAYS["engineering"] == 365 and FRESHNESS_DAYS["measured"] == 365
    assert FRESHNESS_DAYS["used_issues"] == 180


def test_rounds_by_depth():
    assert ROUNDS == {"QUICK": 0, "STANDARD": 1, "DEEP": 2}


def test_plan_skips_fresh_areas_and_researches_stale_ones():
    fresh = {"v1": {"specs": NOW - timedelta(days=10), "price": NOW - timedelta(days=40)}}
    p = plan([car()], persona="BUYER", criteria=[], depth="STANDARD", last_done=fresh, now=NOW)
    areas = {j.area for j in p.jobs}
    assert "specs" not in areas and "price" in areas  # price is older than 30 days
    assert p.rounds == 1
    assert all(j.variant_id == "v1" and j.car_key == "car#1" for j in p.jobs)


def test_plan_nothing_to_do_when_all_fresh():
    areas = areas_for("PERFORMANCE", [], "NEW")
    fresh = {"v1": {a: NOW for a in areas}}
    assert plan([car()], persona="PERFORMANCE", criteria=[], depth="DEEP", last_done=fresh, now=NOW).jobs == []


def test_early_warnings():
    p = plan(
        [car(condition="USED", age=27), car("car#2", "v2", es=False)],
        persona="BUYER",
        criteria=[],
        depth="STANDARD",
        last_done={},
        now=NOW,
    )
    kinds = sorted(w.kind for w in p.warnings)
    assert kinds == ["NOT_SOLD_IN_ES", "OLD_CAR"]


M = SourceHit


@pytest.mark.parametrize(
    ("area", "hits", "ok"),
    [
        ("specs", [M("vw.es", "MANUFACTURER", 5), M("km77.com", "PUBLICATION", 3)], True),
        ("specs", [M("vw.es", "MANUFACTURER", 5)], False),
        ("specs", [M("a.com", "PUBLICATION", 2), M("b.com", "SPEC_DATABASE", 2)], True),
        ("specs", [M("a.com", "PUBLICATION", 2), M("a.com", "PUBLICATION", 2)], False),
        ("maintenance", [M("toyota.es", "MANUFACTURER", 1)], True),
        ("maintenance", [M("a.com", "PUBLICATION", 3)], False),
        ("maintenance", [M("a.com", "PUBLICATION", 1), M("b.com", "PUBLICATION", 1)], True),
        ("reviews", [M("a.com", "PUBLICATION", 3), M("b.com", "PUBLICATION", 2)], True),
        ("reviews", [M("a.com", "PUBLICATION", 4)], False),
        ("reviews", [M("a.com", "PUBLICATION", 2), M("b.com", "PUBLICATION", 2)], False),
        ("reliability", [M("a.com", "PUBLICATION", 1), M("b.com", "PUBLICATION", 1)], True),
        ("reliability", [M("a.com", "PUBLICATION", 5)], False),
        ("price", [M("dacia.es", "MANUFACTURER", 1)], True),
        ("price", [M("a.com", "PUBLICATION", 3)], False),
    ],
)
def test_section_minimums(area, hits, ok):
    assert minimum_met(area, hits) is ok


def test_gaps_only_for_unmet_areas_within_rounds():
    p = plan([car()], persona="BUYER", criteria=[], depth="STANDARD", last_done={}, now=NOW)
    met = {("car#1", j.area): j.area != "reliability" for j in p.jobs}
    g = gaps(p, met, round_done=0)
    assert [(j.car_key, j.area, j.round) for j in g] == [("car#1", "reliability", 1)]
    assert gaps(p, met, round_done=1) == []  # Standard: one follow-up round only


def test_plan_key_identifies_the_same_research():
    from automind.shared.research_order.plan import plan_key

    a = plan([car()], persona="BUYER", criteria=[], depth="STANDARD", last_done={}, now=NOW)
    b = plan([car()], persona="BUYER", criteria=[], depth="DEEP", last_done={}, now=NOW)
    c = plan([car()], persona="BUYER", criteria=["engineering"], depth="STANDARD", last_done={}, now=NOW)
    assert plan_key(a) == plan_key(b) != plan_key(c)


# --- spec 011 T122 (closes 010 T059): a candidate source counts as half an independent source ----------------------


def _h(domain: str, kind: str = "PUBLICATION", *, unverified: bool = False) -> SourceHit:
    return SourceHit(domain, kind, 1, unverified=unverified)


@pytest.mark.parametrize(
    ("area", "hits", "ok"),
    [
        ("used_price", [_h("cand.example", unverified=True)], False),  # 0.5 < 1
        ("used_price", [_h("a.example", unverified=True), _h("b.example", unverified=True)], True),  # 0.5 + 0.5
        ("reliability", [_h("a.example"), _h("cand.example", unverified=True)], False),  # 1.5 < 2
        ("reliability", [_h("a.example"), _h("b.example", unverified=True), _h("c.example", unverified=True)], True),
        ("specs", [_h("a.example", "SPEC_DATABASE", unverified=True), _h("b.example", unverified=True)], False),
        ("specs", [_h("bmw.es", "MANUFACTURER", unverified=True), _h("a.example")], False),  # a candidate brand site
        ("specs", [_h("bmw.es", "MANUFACTURER"), _h("a.example", unverified=True)], False),  # 0.5 non-manufacturer
        ("measured", [_h("lab.example", "INSTRUMENTED_TEST", unverified=True)], False),
        # one verified page of a domain makes the domain verified
        ("used_price", [_h("cand.example", unverified=True), _h("cand.example")], True),
    ],
)
def test_unverified_sources_count_half(area, hits, ok):
    assert minimum_met(area, hits) is ok


def test_stored_hits_without_the_flag_are_verified():
    assert minimum_met("used_price", [SourceHit(**{"domain": "a.example", "source_type": "PUBLICATION", "items": 1})])
