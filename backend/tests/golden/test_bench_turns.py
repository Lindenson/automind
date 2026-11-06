"""Turn latency with and without the worker (spec 011 T059, SC-005). Not run by default:

    uv run pytest tests/golden/test_bench_turns.py -m bench -s   [BENCH_ROUNDS=5] [BENCH_LOAD_PAUSE_S=0]

Every round replays all golden dialogues (fake model from the cassettes, fixture search) twice against the same
database: once with the worker stopped, once with a worker process running background tasks back to back
(tests/golden/bench_load.py: snapshot, reputation, roll-up, parser metrics and prefetch through acquire()). The order
of the two alternates per round. Prints p50/p95 of the turn wall time per mode and the tasks the worker ran.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete

from automind.chat.dialog.runner import ChatRunner
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db import models as m

from .runner import GOLDEN_DIR, run_dialogue

DIALOGUES = sorted(Path(GOLDEN_DIR).glob("g*.yaml"))
BACKEND = Path(__file__).resolve().parents[2]


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100 * len(s) + 0.5) - 1))]


async def _bench_cars() -> list[str]:
    """Two cars asked in far more chats than any golden car: prefetch works on them only."""
    now = datetime.now(UTC)
    vids = []
    async with db.sessionmaker()() as s:
        for name in ("520d 190 CV", "520i 184 CV"):
            v = m.Variant(canonical_key=f"bmw|5 series|g30|{name}|ice|bench-{db.uid()}", make="BMW",
                          model="5 Series", generation="G30", variant_name=name, powertrain="ICE",
                          body_class="SEDAN", generation_years_from=2017, generation_years_to=2023)  # fmt: skip
            s.add(v)
            await s.flush()
            vids.append(v.id)
            for _ in range(500):
                s.add(m.ResearchJob(chat_id=db.uid(), turn_id=db.uid(), variant_id=v.id, area="specs",
                                    status="DONE", started_at=now, finished_at=now))  # fmt: skip
        await s.commit()
    return vids


async def _purge(vids: list[str]) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(delete(m.ResearchJob).where(m.ResearchJob.variant_id.in_(vids)))
        for t in (m.SpecValue, m.Claim, m.ResearchRun, m.PageRelevance, m.RegistryAttempt):
            await s.execute(delete(t).where(t.variant_id.in_(vids)))
        await s.execute(delete(m.Evidence).where(m.Evidence.variant_id.in_(vids)))
        await s.execute(delete(m.Variant).where(m.Variant.id.in_(vids)))
        await s.commit()


async def _start_load() -> asyncio.subprocess.Process:
    p = await asyncio.create_subprocess_exec(sys.executable, "-m", "tests.golden.bench_load", cwd=BACKEND,
                                             env=dict(os.environ), stdout=asyncio.subprocess.PIPE)  # fmt: skip
    assert p.stdout is not None
    line = await asyncio.wait_for(p.stdout.readline(), 60)
    assert line.strip() == b"ready", line
    await asyncio.sleep(1.0)  # the worker is busy before the first turn
    return p


async def _stop_load(p: asyncio.subprocess.Process) -> int:
    p.terminate()
    out, _ = await asyncio.wait_for(p.communicate(), 60)
    return int(json.loads(out.decode().strip().splitlines()[-1])["tasks"])


@pytest.mark.bench
async def test_turn_latency_with_and_without_the_worker(saver, monkeypatch):
    rounds = int(os.environ.get("BENCH_ROUNDS", "5"))
    times: dict[str, list[float]] = {"stopped": [], "running": []}
    mode = {"now": "stopped"}

    def timed(fn):  # noqa: ANN001, ANN202
        async def wrap(self, *a, **k):  # noqa: ANN001, ANN202
            t0 = time.perf_counter()
            try:
                return await fn(self, *a, **k)
            finally:
                times[mode["now"]].append(time.perf_counter() - t0)

        return wrap

    monkeypatch.setattr(ChatRunner, "run_turn", timed(ChatRunner.run_turn))
    monkeypatch.setattr(ChatRunner, "resume", timed(ChatRunner.resume))
    await db.init_db()
    vids = await _bench_cars()
    tasks = 0
    try:
        for r in range(rounds):
            for which in ("stopped", "running") if r % 2 == 0 else ("running", "stopped"):
                mode["now"] = which
                load = await _start_load() if which == "running" else None
                try:
                    for path in DIALOGUES:
                        failures = await run_dialogue(path, saver)
                        assert not failures, "\n".join(failures)
                finally:
                    if load is not None:
                        tasks += await _stop_load(load)
    finally:
        await _purge(vids)
    report = {
        k: {"turns": len(v), "p50_ms": round(1000 * statistics.median(v), 1), "p95_ms": round(1000 * pct(v, 95), 1),
            "mean_ms": round(1000 * statistics.fmean(v), 1)}
        for k, v in times.items()
    }  # fmt: skip
    report["worker_tasks"] = tasks  # type: ignore[assignment]
    print("\nBENCH", json.dumps(report))
    assert tasks > 0 and report["running"]["turns"] == report["stopped"]["turns"]
