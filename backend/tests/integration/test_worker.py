"""Spec 011 T058: the worker runs background work on its own (US2 independent test, constitution XIII).

No API app is created here: the worker is started in-process (and once as a separate process with `--once`), due
tasks are seeded, and the journal `acq_tasks` shows what ran. Two workers never run the same task; shutdown releases
a running task; failures back off and retry; an unknown kind is dead at once.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from automind.acquisition.worker import exporter, queue
from automind.acquisition.worker.budget import BudgetExceeded, BudgetGuard
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import HANDLERS
from automind.acquisition.worker.process import Worker
from automind.infrastructure import db
from automind.infrastructure.db.session import sessionmaker
from automind.insight.metrics import heartbeat


@pytest.fixture(autouse=True)
async def empty_queue():
    await db.init_db()
    async with sessionmaker()() as s:
        await s.execute(text("DELETE FROM acq_tasks"))
        await s.commit()


def _cfg(**worker):
    cfg = worker_config()
    cfg["worker"] = {**cfg["worker"], "poll_s": 0.05, "lease_s": 30, "beat_s": 0.2, "grace_s": 0.2,
                     "schedule_s": 3600, "metrics_port": 0, **worker}  # fmt: skip
    cfg["prefetch"] = {**cfg["prefetch"], "enabled": False}  # the real prefetch is tested in test_prefetch.py
    return cfg


async def _rows(kind: str | None = None) -> list[dict]:
    async with sessionmaker()() as s:
        q = "SELECT * FROM acq_tasks" + (" WHERE kind = :k" if kind else "") + " ORDER BY created_at"
        return [dict(r) for r in (await s.execute(text(q), {"k": kind})).mappings()]


async def _serve_until_done(workers: list[Worker], kind: str, timeout: float = 20) -> None:
    stop = asyncio.Event()
    runs = [asyncio.create_task(w.serve(stop, schedule=False)) for w in workers]
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end and any(r["state"] != "done" for r in await _rows(kind)):
        await asyncio.sleep(0.1)
    stop.set()
    await asyncio.gather(*runs)


async def test_due_background_tasks_run_and_are_journalled_without_the_api():
    for kind in ("metrics_snapshot", "registry_review", "prefetch"):
        await queue.enqueue(kind, {}, dedupe_key=f"{kind}:{uuid.uuid4()}")
    w = Worker(_cfg())
    await w.register()
    done = await w.drain()
    assert len(done) == 3
    rows = {r["kind"]: r for r in await _rows()}
    assert {k: r["state"] for k, r in rows.items()} == {
        "metrics_snapshot": "done", "registry_review": "done", "prefetch": "done"}  # fmt: skip
    assert rows["metrics_snapshot"]["result"]["series"] >= 0
    assert rows["registry_review"]["result"]["autonomy"] is False  # autonomy off: journalled, no source changes
    assert rows["registry_review"]["result"]["changes"] == 0
    assert rows["prefetch"]["result"] == {"skipped": "disabled"}  # off here: tests/integration/test_prefetch.py
    for r in rows.values():
        assert r["locked_by"] == w.id and r["finished_at"] is not None and r["attempts"] == 1
    await w.beat()  # the heartbeat adds the tasks done since the last beat
    async with sessionmaker()() as s:
        reg = (await s.execute(text("SELECT tasks_done, beat_at FROM acq_workers WHERE id = :i"), {"i": w.id})).one()
    assert reg.tasks_done >= 3


async def test_once_runs_in_a_separate_process_without_the_api():
    env = dict(os.environ)  # DATABASE_URL = the test database (tests/conftest.py)
    probe = "import sys; from automind.acquisition.worker.__main__ import main; rc = main(['--once', " \
            "'registry_review']); assert not any(m.startswith('automind.api') for m in sys.modules), " \
            "'the worker imported the API'; sys.exit(rc)"  # fmt: skip
    res = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=120,
                         check=False)  # fmt: skip
    assert res.returncode == 0, res.stdout + res.stderr
    (row,) = await _rows("registry_review")
    assert row["state"] == "done" and row["dedupe_key"].startswith("once:registry_review:")


async def test_scheduler_enqueues_each_period_once():
    w = Worker(_cfg())
    t = datetime(2026, 11, 5, 3, 0, 30, tzinfo=UTC)
    first = await w.tick_schedule(t)
    again = await w.tick_schedule(t + timedelta(seconds=20))
    assert "metrics_snapshot" in first and "registry_review" in first and "insight_run" in first
    assert "prefetch" not in first  # hourly 06-22 UTC only
    assert again == []  # same periods: the dedupe keys exist
    keys = {r["dedupe_key"] for r in await _rows()}
    assert {"snap:2026-11-05T03:00", "review:2026-11-05"} <= keys


async def test_two_workers_never_run_the_same_task():
    ran: Counter[str] = Counter()

    async def slow(task, ctx):
        ran[task.id] += 1
        await asyncio.sleep(0.05)
        return {"by": ctx.worker_id}

    handlers = {**HANDLERS, "test_slow": slow}
    ids = {await queue.enqueue("test_slow", {}, dedupe_key=f"slow:{uuid.uuid4()}") for _ in range(16)}
    a = Worker(_cfg(concurrency=3), handlers=handlers, worker_id=f"a-{uuid.uuid4()}")
    b = Worker(_cfg(concurrency=3), handlers=handlers, worker_id=f"b-{uuid.uuid4()}")
    await _serve_until_done([a, b], "test_slow")
    assert set(ran) == ids and max(ran.values()) == 1
    rows = await _rows("test_slow")
    assert all(r["state"] == "done" for r in rows)
    assert {r["result"]["by"] for r in rows} == {a.id, b.id}  # both took part


async def test_shutdown_releases_a_running_task():
    started = asyncio.Event()

    async def forever(task, ctx):
        started.set()
        await asyncio.sleep(3600)
        return {}

    tid = await queue.enqueue("test_block", {}, dedupe_key=f"block:{uuid.uuid4()}")
    w = Worker(_cfg(grace_s=0.1), handlers={**HANDLERS, "test_block": forever})
    stop = asyncio.Event()
    run = asyncio.create_task(w.serve(stop, schedule=False))
    await asyncio.wait_for(started.wait(), 5)
    assert (await _rows("test_block"))[0]["state"] == "running"
    w.request_stop(stop)  # what the SIGTERM handler calls
    await asyncio.wait_for(run, 5)
    (row,) = await _rows("test_block")
    assert row["id"] == tid and row["state"] == "queued" and row["locked_by"] is None and row["attempts"] == 0


async def test_failure_backs_off_and_retries_then_succeeds():
    calls = []

    async def flaky(task, ctx):
        calls.append(task.attempts)
        if len(calls) == 1:
            raise RuntimeError("source down")
        return {"ok": True}

    before = exporter.failures("test_flaky")
    tid = await queue.enqueue("test_flaky", {}, dedupe_key=f"flaky:{uuid.uuid4()}")
    w = Worker(_cfg(), handlers={**HANDLERS, "test_flaky": flaky})
    await w.drain()
    (row,) = await _rows("test_flaky")
    assert row["state"] == "queued" and "source down" in row["last_error"]
    assert (row["run_at"] - datetime.now(UTC)).total_seconds() > 60  # 2^1 minutes back-off
    assert exporter.failures("test_flaky") == before + 1
    async with sessionmaker()() as s:  # time passes
        await s.execute(text("UPDATE acq_tasks SET run_at = now() WHERE id = :i"), {"i": tid})
        await s.commit()
    await w.drain()
    (row,) = await _rows("test_flaky")
    assert row["state"] == "done" and row["attempts"] == 2 and calls == [1, 2]


async def test_expired_lease_of_a_dead_worker_is_run_by_another():
    tid = await queue.enqueue("prefetch", {}, dedupe_key=f"prefetch:{uuid.uuid4()}")
    await queue.claim("crashed-worker", 1, 30)
    async with sessionmaker()() as s:
        await s.execute(text("UPDATE acq_tasks SET lease_until = now() - interval '1 s' WHERE id = :i"), {"i": tid})
        await s.commit()
    w = Worker(_cfg())
    await w.drain()
    (row,) = await _rows("prefetch")
    assert row["state"] == "done" and row["locked_by"] == w.id and row["attempts"] == 2


async def test_unknown_kind_is_dead_at_once():
    await queue.enqueue("no_such_kind", {}, dedupe_key=f"nk:{uuid.uuid4()}")
    await Worker(_cfg()).drain()
    (row,) = await _rows("no_such_kind")
    assert row["state"] == "dead" and row["last_error"] == "no handler"


async def test_budget_exceeded_completes_with_skipped():
    async def spender(task, ctx):
        await ctx.budget(1.0).charge(5.0)
        return {"spent": True}

    await queue.enqueue("test_spend", {}, dedupe_key=f"spend:{uuid.uuid4()}")
    await Worker(_cfg(), handlers={**HANDLERS, "test_spend": spender}).drain()
    (row,) = await _rows("test_spend")
    assert row["state"] == "done" and row["result"] == {"skipped": "budget"}


async def test_budget_guard_counts_todays_task_spend():
    tid = await queue.enqueue("test_cost", {}, dedupe_key=f"cost:{uuid.uuid4()}")
    await queue.claim("w", 1, 30)
    await queue.complete(tid, {}, cost_eur=0.25)
    g = BudgetGuard("test_cost", 0.30)
    assert await g.remaining() == pytest.approx(0.05)
    await g.charge(0.04)
    with pytest.raises(BudgetExceeded):
        await g.charge(0.02)


async def test_loop_health_comes_from_the_journal():
    w = Worker(_cfg())
    await queue.enqueue("metrics_snapshot", {}, dedupe_key=f"snap:{uuid.uuid4()}")
    await w.drain()
    await w.beat()
    st = heartbeat.state()
    assert st["metrics"]["interval"] == 60
    assert abs(st["metrics"]["last_ok"] - datetime.now(UTC).timestamp()) < 30
    assert "registry" in st and "insight" in st  # every enabled schedule entry is watched
    assert exporter.beat_timestamp() > 0
    assert ("metrics_snapshot", "done") in exporter.task_counts()
