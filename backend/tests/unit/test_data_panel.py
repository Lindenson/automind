"""One data panel instead of a wall of warnings (spec 004 FR-014, FR-015, SC-008)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from automind.application.compose import data_panel_block

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _run(met, accepted=0, docs=0, hours_ago=48):
    return SimpleNamespace(minimum_met=met, claims_accepted=accepted, docs_used=docs,
                           completed_at=NOW - timedelta(hours=hours_ago))  # fmt: skip


def _car(vid, runs, values=3):
    vals = {f"a{i}": SimpleNamespace(available=True) for i in range(values)}
    return {"variant": SimpleNamespace(id=vid), "runs": runs, "values": vals}


def test_status_per_area_and_find_it() -> None:
    car = _car("v1", {"specs": _run(True), "price": _run(False, 1, 2), "reliability": _run(False, 0, 0, hours_ago=2),
                      "maintenance": _run(False, 0, 0, hours_ago=48)})  # fmt: skip
    b = data_panel_block([("car#1", "Mazda CX-5", car)], {"car#1": {"specs", "price", "reliability",
                                                                     "maintenance", "reviews"}}, NOW)  # fmt: skip
    assert b is not None and b["type"] == "data_panel"
    st = {a["area"]: (a["status"], a["findable"]) for a in b["cars"][0]["areas"]}
    assert st["specs"] == ("COMPLETE", False)
    assert st["price"] == ("PARTIAL", True)
    assert st["reliability"] == ("UNAVAILABLE", False)  # searched 2 h ago, nothing: no button yet
    assert st["maintenance"] == ("MISSING", True)  # the retry window has passed
    assert st["reviews"] == ("MISSING", True)  # never researched


def test_panel_says_what_changed_after_find_it() -> None:
    car = _car("v1", {}, values=15)
    b = data_panel_block([("car#1", "CX-5", car)], {"car#1": {"specs"}}, NOW, previous={"car#1": 3})
    assert b is not None and b["changed"] == "+12 values since the last report"
