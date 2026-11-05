"""Spec 011 T039: the Postgres task queue (contracts/task-queue.md, research R6).

Idempotent enqueue by dedupe key, SKIP LOCKED claims, lease reclaim, exponential back-off, dead after max attempts,
lease extension. The queue table is owned by these tests and the worker tests, so each test starts it empty.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from automind.acquisition.worker import queue
from automind.infrastructure import db
from automind.infrastructure.db.session import sessionmaker


@pytest.fixture(autouse=True)
async def empty_queue():
    await db.init_db()
    async with sessionmaker()() as s:
        await s.execute(text("DELETE FROM acq_tasks"))
        await s.commit()


async def _row(task_id: str) -> dict:
    async with sessionmaker()() as s:
        r = (await s.execute(text("SELECT * FROM acq_tasks WHERE id = :i"), {"i": task_id})).mappings().one()
        return dict(r)


async def _set(task_id: str, sql: str) -> None:
    async with sessionmaker()() as s:
        await s.execute(text(f"UPDATE acq_tasks SET {sql} WHERE id = :i"), {"i": task_id})  # noqa: S608 - test only
        await s.commit()


async def test_enqueue_is_idempotent_by_dedupe_key():
    key = f"rollup:{uuid.uuid4()}"
    first = await queue.enqueue("rollup", {"a": 1}, dedupe_key=key)
    second = await queue.enqueue("rollup", {"a": 2}, dedupe_key=key)
    assert first is not None and second is None
    row = await _row(first)
    assert row["state"] == "queued" and row["payload"] == {"a": 1} and row["attempts"] == 0
    assert row["priority"] == 5 and row["max_attempts"] == 3


async def test_concurrent_claims_never_return_the_same_task():
    ids = {await queue.enqueue("drift", {}, dedupe_key=f"drift:{uuid.uuid4()}") for _ in range(12)}
    a, b, c = await asyncio.gather(*(queue.claim(f"w{i}", 8, 60) for i in range(3)))
    got = [t.id for t in (*a, *b, *c)]
    assert len(got) == len(set(got)), "a task was claimed twice"
    assert set(got) == ids
    for t in (*a, *b, *c):
        assert t.state == "running" and t.attempts == 1 and t.locked_by in {"w0", "w1", "w2"}


async def test_a_claim_never_takes_more_than_n():
    """Regression: `WHERE id IN (SELECT … LIMIT n FOR UPDATE SKIP LOCKED)` updated more than n rows under load."""
    for _ in range(30):
        await queue.enqueue("drift", {}, dedupe_key=f"drift:{uuid.uuid4()}")
    got = await asyncio.gather(*(queue.claim(f"w{i}", 1, 60) for i in range(12)))
    assert all(len(g) <= 1 for g in got)
    async with sessionmaker()() as s:
        running = (await s.execute(text("SELECT count(*) FROM acq_tasks WHERE state = 'running'"))).scalar()
    assert running == sum(len(g) for g in got)


async def test_claim_order_and_due_time():
    late = await queue.enqueue("x", {}, dedupe_key=f"x:{uuid.uuid4()}", run_at=db.now() + timedelta(hours=1))
    low = await queue.enqueue("x", {}, dedupe_key=f"x:{uuid.uuid4()}", priority=9)
    high = await queue.enqueue("x", {}, dedupe_key=f"x:{uuid.uuid4()}", priority=1)
    got = await queue.claim("w", 5, 60)
    assert [t.id for t in got] == [high, low]  # lower priority value first; the future task is not due
    assert late not in {t.id for t in got}


async def test_claim_can_be_limited_to_kinds():
    a = await queue.enqueue("alpha", {}, dedupe_key=f"alpha:{uuid.uuid4()}")
    await queue.enqueue("beta", {}, dedupe_key=f"beta:{uuid.uuid4()}")
    got = await queue.claim("w", 5, 60, kinds=["alpha"])
    assert [t.id for t in got] == [a]


async def test_expired_lease_is_reclaimed():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    (t,) = await queue.claim("dead-worker", 1, 60)
    assert await queue.claim("other", 1, 60) == []  # leased: nobody else gets it
    await _set(tid, "lease_until = now() - interval '1 second'")
    (again,) = await queue.claim("other", 1, 60)
    assert again.id == tid and again.locked_by == "other" and again.attempts == 2


async def test_expired_lease_at_max_attempts_turns_dead():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}", max_attempts=1)
    await queue.claim("dead-worker", 1, 60)
    await _set(tid, "lease_until = now() - interval '1 second'")
    assert await queue.claim("other", 1, 60) == []
    row = await _row(tid)
    assert row["state"] == "dead" and "lease" in row["last_error"]


async def test_fail_backs_off_exponentially_then_dead():
    tid = await queue.enqueue("drift", {}, dedupe_key=f"drift:{uuid.uuid4()}", max_attempts=3)
    for attempt in (1, 2):
        (t,) = await queue.claim("w", 1, 60)
        assert t.attempts == attempt
        before = db.now()
        await queue.fail(tid, f"boom {attempt}")
        row = await _row(tid)
        assert row["state"] == "queued" and row["locked_by"] is None and row["lease_until"] is None
        assert row["last_error"] == f"boom {attempt}"
        delay = (row["run_at"] - before).total_seconds()
        assert 2**attempt * 60 - 5 <= delay <= 2**attempt * 60 + 5
        assert await queue.claim("w", 1, 60) == []  # not due yet
        await _set(tid, "run_at = now()")
    await queue.claim("w", 1, 60)
    await queue.fail(tid, "boom 3")
    row = await _row(tid)
    assert row["state"] == "dead" and row["attempts"] == 3 and row["finished_at"] is not None


async def test_extend_moves_the_lease():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    (t,) = await queue.claim("w", 1, 10)
    before = (await _row(tid))["lease_until"]
    await queue.extend(tid, 600)
    after = (await _row(tid))["lease_until"]
    assert (after - before).total_seconds() > 500


async def test_complete_journals_result_and_cost():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    await queue.claim("w", 1, 60)
    assert await queue.complete(tid, {"rows": 3}, cost_eur=0.0123, worker_id="w")
    row = await _row(tid)
    assert row["state"] == "done" and row["result"] == {"rows": 3} and float(row["cost_eur"]) == pytest.approx(0.0123)
    assert row["finished_at"] is not None and row["lease_until"] is None


async def test_complete_by_a_worker_that_lost_the_lease_is_ignored():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    await queue.claim("slow", 1, 60)
    await _set(tid, "lease_until = now() - interval '1 second'")
    await queue.claim("fast", 1, 60)
    assert not await queue.complete(tid, {"by": "slow"}, worker_id="slow")
    assert await queue.complete(tid, {"by": "fast"}, worker_id="fast")
    assert (await _row(tid))["result"] == {"by": "fast"}


async def test_release_returns_the_task_without_counting_the_attempt():
    tid = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    await queue.claim("w", 1, 60)
    await queue.release(tid)
    row = await _row(tid)
    assert row["state"] == "queued" and row["attempts"] == 0 and row["locked_by"] is None
    assert row["lease_until"] is None


async def test_prune_keeps_recent_and_live_tasks():
    old_done = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    old_dead = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    new_done = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    snap = await queue.enqueue("metrics_snapshot", {}, dedupe_key=f"snap:{uuid.uuid4()}")
    queued = await queue.enqueue("rollup", {}, dedupe_key=f"rollup:{uuid.uuid4()}")
    await _set(old_done, "state='done', finished_at = now() - interval '31 days'")
    await _set(old_dead, "state='dead', finished_at = now() - interval '91 days'")
    await _set(new_done, "state='done', finished_at = now() - interval '29 days'")
    await _set(snap, "state='done', finished_at = now() - interval '2 days'")
    await _set(queued, "created_at = now() - interval '200 days'")
    n = await queue.prune(done_days=30, dead_days=90, short={"metrics_snapshot": 1})
    assert n == 3
    async with sessionmaker()() as s:
        left = set((await s.execute(text("SELECT id FROM acq_tasks"))).scalars())
    assert left == {new_done, queued}
