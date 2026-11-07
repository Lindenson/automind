"""python -m automind.cli worker [--once KIND] [--concurrency N] [--metrics-port P] [--metrics-addr A]

The acquisition worker (spec 011 US2, constitution XIII): runs background work from the `acq_tasks` queue in its own
process, so the chat API neither runs it nor stops it. `--once KIND` runs one task of KIND now and prints its
journal row (operator, tests). Metrics on http://<addr>:<port>/metrics (default 127.0.0.1:9101; compose binds
0.0.0.0 inside its network, with no published port).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal

from automind.acquisition.worker import exporter
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import Handler
from automind.acquisition.worker.process import Worker
from automind.shared.infrastructure.llm import gateway as llm_gateway


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m automind.cli worker")
    p.add_argument("--once", metavar="KIND", help="run one task of KIND now and exit")
    p.add_argument("--concurrency", type=int, help="tasks at once (default worker.concurrency)")
    p.add_argument("--metrics-port", type=int, help="exporter port (default worker.metrics_port; 0 = off)")
    p.add_argument("--metrics-addr", default=os.environ.get("AUTOMIND_WORKER_METRICS_ADDR", "127.0.0.1"))
    return p.parse_args(argv)


async def run(a: argparse.Namespace, handlers: dict[str, Handler] | None = None) -> int:
    """Run the worker until stopped (or one task with `--once`). `handlers`: every task kind's handler, as the
    composition root assembles them (None: the engine's own, `handlers.HANDLERS`)."""
    cfg = worker_config()
    # the worker's own limit on model calls in flight (worker.llm_concurrency), apart from the API's turns
    llm_gateway._LLM_SEM[id(asyncio.get_running_loop())] = asyncio.Semaphore(  # noqa: SLF001
        int(cfg["worker"]["llm_concurrency"])
    )
    worker = Worker(cfg, concurrency=a.concurrency, handlers=handlers)
    if a.once:
        await worker.register()
        row = await worker.once(a.once)
        await worker.beat()
        print(json.dumps(row, default=str, ensure_ascii=False))
        return 0 if row["state"] == "done" else 1
    port = cfg["worker"]["metrics_port"] if a.metrics_port is None else a.metrics_port
    exporter.start(int(port or 0), a.metrics_addr)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.request_stop, stop)
    await worker.serve(stop)
    return 0
