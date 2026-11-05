"""The worker: N claim loops, the scheduler, the heartbeat (contracts/task-queue.md "Process").

A claimed task runs its handler with `current_job = (task id, …)`, so its model calls carry the task id as
`llm_calls.job_id`; its lease is extended every `lease_s/3`. Success → `done` with the result and the spend;
`BudgetExceeded` → `done` with `{"skipped": "budget"}`; an error → back-off or `dead` (queue.fail); shutdown →
the task is released (queued again, the attempt does not count).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import text

from automind.acquisition.worker import exporter, heartbeat, queue, scheduler
from automind.acquisition.worker.budget import BudgetExceeded
from automind.acquisition.worker.config import worker_config
from automind.acquisition.worker.handlers import AWAITING_HANDLER, HANDLERS, Handler, WorkerCtx
from automind.application.usage import current_job
from automind.infrastructure.db.models import now
from automind.infrastructure.db.session import sessionmaker

log = logging.getLogger(__name__)


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


class Worker:
    def __init__(self, cfg: dict[str, Any] | None = None, *, worker_id: str | None = None,
                 handlers: dict[str, Handler] | None = None, concurrency: int | None = None,
                 kinds: Sequence[str] | None = None) -> None:  # fmt: skip
        self.cfg = cfg or worker_config()
        w = self.cfg["worker"]
        self.id = worker_id or f"{socket.gethostname()[:40]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.handlers = handlers or HANDLERS
        self.concurrency = max(1, int(concurrency or w["concurrency"]))
        self.kinds = list(kinds) if kinds else None
        self.skip = [k for k in AWAITING_HANDLER if k not in self.handlers]  # left queued until their story lands
        self.lease_s = int(w["lease_s"])
        self.poll_s, self.beat_s = float(w["poll_s"]), float(w["beat_s"])
        self.schedule_s, self.grace_s = float(w["schedule_s"]), float(w["grace_s"])
        self.started: datetime = now()
        self._done = 0

    # --- bookkeeping ----------------------------------------------------------------------------------------------

    async def register(self) -> None:
        await heartbeat.register(self.id)
        exporter.beat(self.id)

    async def beat(self) -> None:
        done, self._done = self._done, 0
        await heartbeat.beat(self.id, done)
        await heartbeat.refresh_gauges(self.cfg.get("schedule") or {}, self.started)

    @staticmethod
    async def seed() -> None:
        """Spec 011 T086: today's site readers become parser spec version 1 (idempotent)."""
        from automind.acquisition.parsing.migrate_v1 import seed  # noqa: PLC0415

        try:
            got = await seed()
            if got["inserted"]:
                log.info("worker.parsers_seeded %s", got)
        except Exception:  # noqa: BLE001 - the readers fall back to the YAML; never stop the worker
            log.warning("worker.parser_seed_failed", exc_info=True)

    async def tick_schedule(self, at: datetime | None = None) -> list[str]:
        return await scheduler.tick(self.cfg.get("schedule") or {}, at)

    @staticmethod
    async def schema_ready() -> bool:
        async with sessionmaker()() as s:
            return bool((await s.execute(text("SELECT to_regclass('acq_tasks') IS NOT NULL"))).scalar())

    # --- running one task -----------------------------------------------------------------------------------------

    async def _extend(self, task_id: str) -> None:
        while True:
            await asyncio.sleep(max(1.0, self.lease_s / 3))
            try:
                await queue.extend(task_id, self.lease_s)
            except Exception:  # noqa: BLE001 - a missed extension only risks a re-run (handlers are idempotent)
                log.warning("worker.extend_failed task=%s", task_id, exc_info=True)

    @staticmethod
    async def _llm_cost(task_id: str) -> float:
        async with sessionmaker()() as s:
            q = text("SELECT coalesce(sum(cost_eur), 0) FROM llm_calls WHERE job_id = :i")
            return float((await s.execute(q, {"i": task_id})).scalar() or 0)

    async def run_task(self, task: queue.Task) -> None:
        handler = self.handlers.get(task.kind)
        if handler is None:
            await queue.bury(task.id, "no handler")
            exporter.observe(task.kind, 0, False)
            return
        ctx = WorkerCtx(self.id, self.cfg, task)
        token = current_job.set(cast(tuple[str, str], (task.id, None)))  # model calls carry the task id
        extender = asyncio.create_task(self._extend(task.id))
        t0 = time.monotonic()
        try:
            try:
                result = await handler(task, ctx)
            except BudgetExceeded as e:
                log.info("worker.budget kind=%s %s", task.kind, e)
                result = {"skipped": "budget"}
            cost = await self._llm_cost(task.id) + ctx.charged
            if await queue.complete(task.id, result, cost, worker_id=self.id):
                self._done += 1
            exporter.observe(task.kind, time.monotonic() - t0, True)
            log.info("worker.done kind=%s key=%s %s", task.kind, task.dedupe_key, result)
        except asyncio.CancelledError:
            await asyncio.shield(queue.release(task.id, worker_id=self.id))
            log.info("worker.released kind=%s key=%s", task.kind, task.dedupe_key)
            raise
        except Exception as e:  # noqa: BLE001 - a failing task never stops the worker
            log.exception("worker.failed kind=%s key=%s", task.kind, task.dedupe_key)
            exporter.observe(task.kind, time.monotonic() - t0, False)
            await queue.fail(task.id, f"{type(e).__name__}: {e}", worker_id=self.id)
        finally:
            extender.cancel()
            current_job.reset(token)

    async def drain(self) -> list[str]:
        """Run every due task now (tests, `--once`); returns the ids run."""
        ran: list[str] = []
        while tasks := await queue.claim(self.id, self.concurrency, self.lease_s, self.kinds, self.skip):
            await asyncio.gather(*(self.run_task(t) for t in tasks))
            ran += [t.id for t in tasks]
        return ran

    async def once(self, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Enqueue one task of `kind` now, run it here and return its journal row."""
        key = f"once:{kind}:{uuid.uuid4()}"
        tid = await queue.enqueue(kind, payload or {}, dedupe_key=key, priority=0)
        for task in await queue.claim(self.id, 1, self.lease_s, [kind]):
            await self.run_task(task)
        async with sessionmaker()() as s:
            q = text("SELECT state, result, last_error, cost_eur FROM acq_tasks WHERE id = :i")
            row = (await s.execute(q, {"i": tid})).mappings().one()
        return {"id": tid, **dict(row), "cost_eur": float(row["cost_eur"] or 0)}

    # --- the long-running process ---------------------------------------------------------------------------------

    def request_stop(self, stop: asyncio.Event) -> None:
        """SIGTERM/SIGINT: stop claiming; running tasks get `grace_s`, then they are released."""
        if not stop.is_set():
            log.info("worker.stopping id=%s", self.id)
        stop.set()

    async def _claim_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                tasks = await queue.claim(self.id, 1, self.lease_s, self.kinds, self.skip)
            except Exception:  # noqa: BLE001 - the database may be restarting
                log.warning("worker.claim_failed", exc_info=True)
                tasks = []
            if not tasks:
                await _wait(stop, self.poll_s)
                continue
            for task in tasks:
                await self.run_task(task)

    async def _every(self, stop: asyncio.Event, seconds: float, what: str, fn: Any) -> None:
        while not stop.is_set():
            try:
                await fn()
            except Exception:  # noqa: BLE001 - bookkeeping must never stop the worker
                log.warning("worker.%s_failed", what, exc_info=True)
            await _wait(stop, seconds)

    async def serve(self, stop: asyncio.Event, *, schedule: bool = True) -> None:
        while not await self.schema_ready():  # the app's container runs the migrations
            log.info("worker.waiting_for_migrations")
            await _wait(stop, 5)
            if stop.is_set():
                return
        await self.register()
        await self.seed()
        log.info("worker.started id=%s concurrency=%s", self.id, self.concurrency)
        claims = [asyncio.create_task(self._claim_loop(stop)) for _ in range(self.concurrency)]
        side = [asyncio.create_task(self._every(stop, self.beat_s, "beat", self.beat))]
        if schedule:
            side.append(asyncio.create_task(self._every(stop, self.schedule_s, "schedule", self.tick_schedule)))
        await stop.wait()
        _done, pending = await asyncio.wait(claims, timeout=self.grace_s)
        for t in pending:  # still running after the grace period: cancelled, the task is released
            t.cancel()
        await asyncio.gather(*claims, *side, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self.beat()
        log.info("worker.stopped id=%s", self.id)
