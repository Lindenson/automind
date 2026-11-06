"""Worker registration and heartbeat (`acq_workers`), and the loop health of the periodic tasks.

Every `beat_s` a worker writes `beat_at`, sets `automind_worker_beat_timestamp_seconds`, refreshes the
`automind_acq_tasks{kind,state}` gauge and derives the `automind_loop_*` health of each enabled schedule entry from
the journal: last success = the newest `done` task of the kind; fails in a row = its failed attempts since then.
A kind that never ran yet counts as healthy from the worker's start (like the 010 loops did).
"""

from __future__ import annotations

import os
import socket
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.worker import exporter, queue, scheduler
from automind.observability.metrics import heartbeat as loops
from automind.shared.infrastructure.db.models import AcqWorker, now
from automind.shared.infrastructure.db.session import sessionmaker


def version() -> str:
    return os.environ.get("AUTOMIND_VERSION") or os.environ.get("GIT_COMMIT") or "dev"


async def register(worker_id: str) -> None:
    t = now()
    stmt = insert(AcqWorker).values(id=worker_id, host=socket.gethostname()[:120], pid=os.getpid(),
                                    version=version()[:80], started_at=t, beat_at=t, tasks_done=0)  # fmt: skip
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_={"started_at": t, "beat_at": t, "pid": os.getpid()})
    async with sessionmaker()() as s:
        await s.execute(stmt)
        await s.commit()


async def beat(worker_id: str, done: int = 0) -> None:
    async with sessionmaker()() as s:
        await s.execute(
            text("UPDATE acq_workers SET beat_at = now(), tasks_done = tasks_done + :d WHERE id = :i"),
            {"i": worker_id, "d": int(done)},
        )
        await s.commit()
    exporter.beat(worker_id)


_HEALTH = text(
    """
    SELECT kind,
           max(finished_at) FILTER (WHERE state = 'done') AS last_ok,
           count(*) FILTER (WHERE last_error IS NOT NULL AND state IN ('queued', 'running', 'dead')
                            AND coalesce(finished_at, run_at) > coalesce(
                                (SELECT max(d.finished_at) FROM acq_tasks d
                                 WHERE d.kind = t.kind AND d.state = 'done'), '-infinity')) AS fails
    FROM acq_tasks t WHERE kind = ANY(:kinds) GROUP BY kind
    """
)


async def refresh_gauges(schedule: dict[str, Any], started: datetime) -> None:
    exporter.set_counts(await queue.counts())
    try:  # spec 011 T110: open gated changes by agent and phase, agents' spend today and budgets
        from automind.acquisition.gates import journal  # noqa: PLC0415

        await journal.publish_gauges()
    except Exception:  # noqa: BLE001 - gauges are best effort
        pass
    entries = scheduler.enabled(schedule)
    if not entries:
        return
    async with sessionmaker()() as s:
        rows = {r.kind: r for r in (await s.execute(_HEALTH, {"kinds": list(entries)})).all()}
    for kind, e in entries.items():
        r = rows.get(kind)
        last = r.last_ok.timestamp() if r is not None and r.last_ok is not None else started.timestamp()
        loops.restore(str(e.get("loop") or kind), last, float(r.fails if r is not None else 0),
                      scheduler.interval_s(e))  # fmt: skip
