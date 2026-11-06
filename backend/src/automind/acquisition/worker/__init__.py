"""Acquisition · acquisition.worker: the background process — a Postgres task queue run outside the API process.

Owns:
  `queue` — the task queue (`acq_tasks`): enqueue, claim (FOR UPDATE SKIP LOCKED), complete, fail, prune.
  `process` — the worker: N claim loops, the scheduler, the heartbeat; `scheduler` — periodic tasks due now.
  `handlers` — HANDLERS[kind](task, ctx): one handler per task kind.
  `budget` — daily budgets per task kind; `heartbeat` — worker registration and loop health.
  `prefetch` — refresh the most asked cars before users ask; `exporter` — the worker's Prometheus exporter.
  `config` — worker settings from config/acquisition.yaml.
  `entry` — the worker process (arguments, start, `--once`), run by `python -m automind.cli worker`.
Flow: scheduler.tick → queue.enqueue → process claims → handlers[kind] (budget checked) → queue.complete / fail.
Depends on: agents, drift, gates, parsing, registry, reputation, snapshots, infrastructure,
  shared (infrastructure, metering), observability (metrics, loop); prometheus_client, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
Note: the worker also runs observability jobs (metrics snapshot, the insight loop), not only acquisition work.
"""

__all__: list[str] = [
    "budget",
    "config",
    "entry",
    "exporter",
    "handlers",
    "heartbeat",
    "prefetch",
    "process",
    "queue",
    "scheduler",
]
