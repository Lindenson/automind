"""The Postgres task queue (spec 011 contracts/task-queue.md, research R6).

Any process may `enqueue`; only workers `claim`. A claim is one statement with `FOR UPDATE SKIP LOCKED`, so two
workers never get the same task; a running task whose lease expired (its worker died) is claimed again, or turns
`dead` when it has used all its attempts. Failures go back to `queued` with an exponential back-off
(`2^attempts` minutes) and turn `dead` at `max_attempts`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from automind.infrastructure.db.models import AcqTask, now, uid
from automind.infrastructure.db.session import sessionmaker

STATES = ("queued", "running", "done", "failed", "dead")


@dataclass(frozen=True)
class Task:
    id: str
    kind: str
    dedupe_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    state: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    run_at: datetime | None = None
    lease_until: datetime | None = None
    locked_by: str | None = None


def _task(r: Any) -> Task:
    return Task(id=r.id, kind=r.kind, dedupe_key=r.dedupe_key, payload=dict(r.payload or {}), priority=r.priority,
                state=r.state, attempts=r.attempts, max_attempts=r.max_attempts, run_at=r.run_at,
                lease_until=r.lease_until, locked_by=r.locked_by)  # fmt: skip


async def enqueue(kind: str, payload: dict[str, Any], *, dedupe_key: str, run_at: datetime | None = None,
                  priority: int = 5, max_attempts: int = 3) -> str | None:  # fmt: skip
    """Add a task; None when a task with this dedupe key already exists (idempotent)."""
    stmt = (
        insert(AcqTask)
        .values(
            id=uid(),
            kind=kind,
            dedupe_key=dedupe_key,
            payload=payload,
            priority=priority,
            state="queued",
            run_at=run_at or now(),
            attempts=0,
            max_attempts=max_attempts,
            cost_eur=0,
            created_at=now(),
        )  # fmt: skip
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(AcqTask.id)
    )
    async with sessionmaker()() as s:
        got = (await s.execute(stmt)).scalar_one_or_none()
        await s.commit()
    return got


# Expired leases of tasks that used all their attempts: the worker died on the last one.
_BURY = text(
    """
    UPDATE acq_tasks SET state = 'dead', finished_at = now(), lease_until = NULL,
           last_error = coalesce(last_error || ' / ', '') || 'lease expired on the last attempt (' || locked_by || ')'
    WHERE state = 'running' AND lease_until < now() AND attempts >= max_attempts
    """
)

# Research R6's statement, with the candidates in a MATERIALIZED CTE: as `WHERE id IN (SELECT … LIMIT n FOR UPDATE
# SKIP LOCKED)` Postgres may run the sub-select more than once and update more than n rows (seen under load).
_CLAIM = """
    WITH picked AS MATERIALIZED (
        SELECT id FROM acq_tasks
        WHERE ((state = 'queued' AND run_at <= now())
               OR (state = 'running' AND lease_until < now() AND attempts < max_attempts))
          {kinds}
        ORDER BY priority, run_at LIMIT :n FOR UPDATE SKIP LOCKED)
    UPDATE acq_tasks t SET state = 'running', locked_by = :w, started_at = now(), attempts = t.attempts + 1,
           lease_until = now() + make_interval(secs => :lease)
    FROM picked WHERE t.id = picked.id
    RETURNING t.id, t.kind, t.dedupe_key, t.payload, t.priority, t.state, t.attempts, t.max_attempts, t.run_at,
              t.lease_until, t.locked_by
"""


async def claim(worker_id: str, n: int, lease_s: int, kinds: Sequence[str] | None = None) -> list[Task]:
    """Take up to n due tasks (or tasks whose lease expired) for this worker; never one another worker holds."""
    if kinds:
        stmt = text(_CLAIM.format(kinds="AND kind IN :kinds")).bindparams(bindparam("kinds", expanding=True))
        params: dict[str, Any] = {"kinds": list(kinds)}
    else:
        stmt, params = text(_CLAIM.format(kinds="")), {}
    async with sessionmaker()() as s:
        await s.execute(_BURY)
        rows = (await s.execute(stmt, {"w": worker_id, "lease": float(lease_s), "n": int(n), **params})).all()
        await s.commit()
    return sorted((_task(r) for r in rows), key=lambda t: (t.priority, t.run_at or now()))


async def extend(task_id: str, lease_s: int) -> None:
    async with sessionmaker()() as s:
        await s.execute(
            text(
                "UPDATE acq_tasks SET lease_until = now() + make_interval(secs => :l) "
                "WHERE id = :i AND state = 'running'"
            ),  # fmt: skip
            {"i": task_id, "l": float(lease_s)},
        )
        await s.commit()


async def complete(task_id: str, result: dict[str, Any], cost_eur: float = 0, *, worker_id: str | None = None) -> bool:
    """Mark a running task done. With worker_id, only while that worker still holds it (a lost lease is ignored)."""
    async with sessionmaker()() as s:
        q = (
            AcqTask.__table__.update()
            .where(AcqTask.id == task_id, AcqTask.state == "running")
            .values(
                state="done",
                result=result,
                cost_eur=round(float(cost_eur or 0), 4),
                finished_at=func.now(),
                lease_until=None,
            )  # fmt: skip
        )
        if worker_id is not None:
            q = q.where(AcqTask.locked_by == worker_id)
        n = (await s.execute(q)).rowcount or 0
        await s.commit()
    return n > 0


async def fail(task_id: str, error: str, *, worker_id: str | None = None) -> str | None:
    """Back off 2^attempts minutes, or `dead` at max_attempts. Returns the new state (None when not held)."""
    guard = "AND locked_by = :w" if worker_id is not None else ""
    sql = f"""
        UPDATE acq_tasks SET
            state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'queued' END,
            run_at = CASE WHEN attempts >= max_attempts THEN run_at
                          ELSE now() + make_interval(mins => power(2, attempts)::int) END,
            finished_at = CASE WHEN attempts >= max_attempts THEN now() END,
            lease_until = NULL, locked_by = NULL, last_error = :e
        WHERE id = :i AND state = 'running' {guard}
        RETURNING state
    """  # noqa: S608 - the only interpolation is a fixed clause
    async with sessionmaker()() as s:
        state = (await s.execute(text(sql), {"i": task_id, "e": error[:4000], "w": worker_id})).scalar_one_or_none()
        await s.commit()
    return state


async def bury(task_id: str, error: str) -> None:
    """Dead at once (an unknown kind: retrying cannot help)."""
    async with sessionmaker()() as s:
        await s.execute(
            AcqTask.__table__.update()
            .where(AcqTask.id == task_id)
            .values(state="dead", last_error=error, finished_at=func.now(), lease_until=None)
        )
        await s.commit()


async def release(task_id: str, *, worker_id: str | None = None) -> None:
    """Give a running task back (shutdown): queued again, the interrupted attempt does not count."""
    async with sessionmaker()() as s:
        q = (
            AcqTask.__table__.update()
            .where(AcqTask.id == task_id, AcqTask.state == "running")
            .values(
                state="queued",
                lease_until=None,
                locked_by=None,
                started_at=None,
                attempts=func.greatest(AcqTask.attempts - 1, 0),
            )  # fmt: skip
        )
        if worker_id is not None:
            q = q.where(AcqTask.locked_by == worker_id)
        await s.execute(q)
        await s.commit()


async def prune(done_days: int = 30, dead_days: int = 90, short: dict[str, int] | None = None) -> int:
    """Delete old finished tasks (data-model: done 30 days, dead 90); `short` keeps frequent kinds for fewer days."""
    t = now()

    conds = [
        (AcqTask.state == "done") & (AcqTask.finished_at < t - timedelta(days=done_days)),
        (AcqTask.state.in_(("dead", "failed"))) & (AcqTask.finished_at < t - timedelta(days=dead_days)),
    ]
    for kind, days in (short or {}).items():
        conds.append(
            (AcqTask.kind == kind) & (AcqTask.state == "done") & (AcqTask.finished_at < t - timedelta(days=days))
        )
    async with sessionmaker()() as s:
        n = (await s.execute(delete(AcqTask).where(or_(*conds)))).rowcount or 0
        await s.commit()
    return n


async def counts() -> list[tuple[str, str, int]]:
    """(kind, state, n) over the whole table, for the worker's gauge."""
    async with sessionmaker()() as s:
        rows = await s.execute(select(AcqTask.kind, AcqTask.state, func.count()).group_by(AcqTask.kind, AcqTask.state))
        return [(k, st, int(n)) for k, st, n in rows.all()]
