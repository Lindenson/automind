"""python -m automind.acquisition.worker [--once KIND] [--concurrency N] [--metrics-port P] [--metrics-addr A]

The acquisition worker (spec 011 US2, constitution XIII): runs background work from the `acq_tasks` queue in its own
process, so the chat API neither runs it nor stops it. `--once KIND` runs one task of KIND now and prints its
journal row (operator, tests). Metrics on http://<addr>:<port>/metrics (default 127.0.0.1:9101; compose binds
0.0.0.0 inside its network, with no published port).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys

from automind.acquisition.worker import exporter
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.process import Worker
from automind.shared.infrastructure.config.loader import configure_domain
from automind.shared.infrastructure.llm import gateway as llm_gateway


def _args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m automind.acquisition.worker")
    p.add_argument("--once", metavar="KIND", help="run one task of KIND now and exit")
    p.add_argument("--concurrency", type=int, help="tasks at once (default worker.concurrency)")
    p.add_argument("--metrics-port", type=int, help="exporter port (default worker.metrics_port; 0 = off)")
    p.add_argument("--metrics-addr", default=os.environ.get("AUTOMIND_WORKER_METRICS_ADDR", "127.0.0.1"))
    return p.parse_args(argv)


async def _main(a: argparse.Namespace) -> int:
    cfg = worker_config()
    # the worker's own limit on model calls in flight (worker.llm_concurrency), apart from the API's turns
    llm_gateway._LLM_SEM[id(asyncio.get_running_loop())] = asyncio.Semaphore(  # noqa: SLF001
        int(cfg["worker"]["llm_concurrency"])
    )
    worker = Worker(cfg, concurrency=a.concurrency)
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


def main(argv: list[str] | None = None) -> int:
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format=fmt)
    configure_domain()
    return asyncio.run(_main(_args(sys.argv[1:] if argv is None else argv)))


if __name__ == "__main__":
    sys.exit(main())
