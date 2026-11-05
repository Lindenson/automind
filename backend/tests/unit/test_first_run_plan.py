"""Spec 010 FR-022 (live chats 5821ac77 / d7edfc29 / 2f8b0018): an area an earlier run left below its minimum
without trying the registry's sources on the other markets is researched again in the first research of a turn,
escalated, whatever the 12-hour retry window says; once tried, it waits for the window."""

from datetime import UTC, datetime, timedelta

from automind.domain import research_plan as rp

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
CAR = rp.CarToPlan(key="car#1", variant_id="v1", condition="NEW")
DONE = {"v1": {a: NOW - timedelta(hours=1) for a in rp.AREAS}}  # everything cached an hour ago


def _plan(registry_done=None, unmet=None, force=None):  # noqa: ANN001, ANN202
    return rp.plan([CAR], persona="BUYER", criteria=[], depth="STANDARD", last_done=DONE, now=NOW,
                   unmet=unmet if unmet is not None else {"v1": {"specs", "price", "reliability"}},
                   registry_done=registry_done, force=force)  # fmt: skip


def test_short_areas_never_tried_on_the_registry_are_escalated_now() -> None:
    p = _plan()
    assert sorted((j.area, j.escalate, j.fresh) for j in p.jobs) == [
        ("price", True, False), ("reliability", True, False), ("specs", True, False),
    ]  # fmt: skip


def test_short_areas_tried_on_the_registry_recently_wait_for_the_retry_window() -> None:
    tried = {"v1": {"specs": NOW - timedelta(days=1), "price": NOW - timedelta(days=8)}}
    p = _plan(registry_done=tried)
    assert sorted((j.area, j.escalate) for j in p.jobs) == [("price", True), ("reliability", True)]


def test_met_areas_stay_cached_and_find_it_keeps_its_own_flag() -> None:
    assert _plan(unmet={}).jobs == []
    p = _plan(force={"v1": {"price"}})
    price = next(j for j in p.jobs if j.area == "price")
    assert price.fresh and not price.escalate  # "find it" already tries every market, past the cache


def test_a_gap_round_after_an_escalated_round_stays_bounded_by_depth() -> None:
    p = _plan()
    nxt = rp.gaps(p, {}, round_done=0)
    assert {j.round for j in nxt} == {1} and rp.gaps(p, {}, round_done=1) == []
