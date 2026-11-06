"""Background load for the turn-latency bench (spec 011 T059, SC-005): a worker in its own process, as deployed.

`python -m tests.golden.bench_load` (DATABASE_URL = the test database) runs, until SIGTERM, back to back: the
journal-heavy kinds (`metrics_snapshot`, `reputation_signals`, `rollup`, `parser_daily`) and `prefetch` through
`acquire()` with the fixture search and a fake model on the bench cars (seeded by the bench as the most asked, so the
golden dialogues' cars are never touched). Back to back (the default) is a worst case: the real worker is idle most of
the time; `BENCH_LOAD_PAUSE_S` pauses between batches. On exit it prints `{"tasks": N}`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import uuid

from automind.acquisition.worker import prefetch, queue
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import HANDLERS
from automind.acquisition.worker.process import Worker
from automind.shared.infrastructure.config.loader import configure_domain
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch

KINDS = ("metrics_snapshot", "reputation_signals", "rollup", "parser_daily", "prefetch")


def _extractor(system, user):  # noqa: ANN001, ANN202
    claim = {"attribute": "max_power", "raw_value": "190", "unit": "CV", "excerpt": "190 CV", "scope": "VARIANT"}
    return {"is_about_variant": True, "claims": [claim]}


def _ports():  # noqa: ANN202
    from tests.graph.conftest import engine, make_ports  # noqa: PLC0415

    llm = FakeLLM()
    llm.responders["extractor"] = _extractor
    llm.responders["validator"] = lambda s, u: {"verdicts": [{"index": 0, "verdict": "OTHER_MARKET"}]}
    return engine(make_ports(llm=llm, search=FixtureSearch("bmw520")))


async def _main() -> int:
    cfg = worker_config()
    cfg["worker"] = {**cfg["worker"], "metrics_port": 0, "poll_s": 0.05}
    # always due, never out of budget, only the bench cars (they lead the popularity by far)
    cfg["prefetch"] = {**cfg["prefetch"], "enabled": True, "eur_per_day": 1e6, "short_retry_h": 0,
                       "due_within_h": 1e6, "variants_per_run": 2, "jobs_per_run": 2, "busy_min": 0}  # fmt: skip

    async def pf(task, ctx):  # noqa: ANN001, ANN202
        return await prefetch.run(task, ctx, ports=_ports())

    w = Worker(cfg, handlers={**HANDLERS, "prefetch": pf}, kinds=list(KINDS), concurrency=2)
    await w.register()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    done = 0
    pause = float(os.environ.get("BENCH_LOAD_PAUSE_S") or 0)  # 0: back to back (worst case)
    print("ready", flush=True)
    while not stop.is_set():
        for kind in KINDS:
            await queue.enqueue(kind, {}, dedupe_key=f"bench:{kind}:{uuid.uuid4()}")
        done += len(await w.drain())
        if pause:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), pause)
    print(json.dumps({"tasks": done}), flush=True)
    return 0


if __name__ == "__main__":
    configure_domain()
    sys.exit(asyncio.run(_main()))
