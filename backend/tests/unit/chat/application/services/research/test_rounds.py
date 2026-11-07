"""Research rounds (chat/application/services/research/rounds.py): the plan as the turn state carries it, what the
engine is asked for, the minimum per car × area, and a limit reached — including the shapes older checkpoints hold."""

from __future__ import annotations

from automind.acquisition import api as acquisition
from automind.chat.application.services.research import rounds
from automind.chat.application.services.research.contracts import JobResult, JobState


def _job(**kw: object) -> JobState:
    base: JobState = {"job_id": "j1", "car_key": "car#1", "variant_id": "v1", "area": "specs", "round": 0,
                      "fresh": False, "escalate": False}  # fmt: skip
    return {**base, **kw}  # type: ignore[typeddict-item]  # test shorthand


def test_plan_of_reads_rows_with_or_without_the_flags() -> None:
    plan = rounds.plan_of({"jobs": [["car#1", "v1", "specs", True, True], ["car#2", "v2", "price"]], "rounds": 2})
    assert [(j.car_key, j.area, j.fresh, j.escalate) for j in plan.jobs] == [
        ("car#1", "specs", True, True), ("car#2", "price", False, False)]  # fmt: skip
    assert plan.rounds == 2 and rounds.plan_of(None).jobs == []


def test_need_of_prefers_fresh_then_escalate_then_round() -> None:
    assert rounds.need_of(_job(fresh=True, escalate=True)) == acquisition.Need.FRESH
    assert rounds.need_of(_job(escalate=True)) == acquisition.Need.ESCALATE
    assert rounds.need_of(_job(round=1)) == acquisition.Need.FOLLOW_UP
    assert rounds.need_of(_job()) == acquisition.Need.STANDARD


def test_minimum_met_later_round_wins_and_reused_counts_as_met() -> None:
    results: list[JobResult] = [
        {**_job(), "ok": True, "minimum_met": False},
        {**_job(round=1), "ok": True, "minimum_met": True},
        {**_job(area="price"), "ok": True, "reused": True, "minimum_met": None},
    ]
    assert rounds.minimum_met(results) == {("car#1", "specs"): True, ("car#1", "price"): True}


def test_limit_hit_names_the_reasons_and_the_jobs_to_run_again() -> None:
    stopped: JobResult = {**_job(fresh=True), "ok": False, "limit": "cost"}
    other: JobResult = {**_job(job_id="old"), "ok": False, "limit": "calls"}  # not of this round
    hit = rounds.limit_hit([stopped, other], {"j1"})
    assert hit == {"reasons": ["cost"], "jobs": [{"car_key": "car#1", "variant_id": "v1", "area": "specs", "round": 0,
                                                  "fresh": True, "escalate": False}]}  # fmt: skip
    assert [(j.area, j.fresh) for j in rounds.jobs_of(hit)] == [("specs", True)]
    assert rounds.limit_hit([{**_job(), "ok": True}], {"j1"}) is None


def test_limit_hit_reads_an_older_checkpoint() -> None:
    old = {"job_id": "j1", "car_key": "car#1", "variant_id": "v1", "area": "specs", "round": 0, "limit": True}
    hit = rounds.limit_hit([old], {"j1"})  # type: ignore[list-item]  # no flags, limit True: written before 2026-11
    assert hit is not None and hit["reasons"] == [rounds.DEFAULT_LIMIT]
    assert (hit["jobs"][0]["fresh"], hit["jobs"][0]["escalate"]) == (False, False)
