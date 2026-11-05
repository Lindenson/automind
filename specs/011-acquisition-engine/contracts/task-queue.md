# Contract: Worker and task queue (`automind.acquisition.worker`)

## Process

- Start: `python -m automind.acquisition.worker [--once KIND] [--concurrency N]`; compose service `worker` (same image
  as `app`, `command: ["python", "-m", "automind.acquisition.worker"]`, env files `.env`, `.env.docker`,
  `depends_on: postgres: service_healthy`, `restart: unless-stopped`, no host port; metrics on `worker:9101` inside
  the compose network). `scripts/dev.sh` starts it in the background unless `--no-worker`.
- On start: register in `acq_workers`; on SIGTERM: stop claiming, finish or release running tasks (state back to
  `queued`, `lease_until = null`), exit within 30 s.
- Heartbeat every 15 s (`acq_workers.beat_at`, gauge `automind_worker_beat_timestamp_seconds`).

## Queue API (`acquisition/worker/queue.py`)

```python
async def enqueue(kind: str, payload: dict, *, dedupe_key: str, run_at: datetime | None = None,
                  priority: int = 5, max_attempts: int = 3) -> str | None   # None when the key exists (idempotent)
async def claim(worker_id: str, n: int, lease_s: int) -> list[Task]          # FOR UPDATE SKIP LOCKED (research R6)
async def extend(task_id: str, lease_s: int) -> None
async def complete(task_id: str, result: dict, cost_eur: float = 0) -> None
async def fail(task_id: str, error: str) -> None                            # back-off 2^attempts min, dead at max
```

- Any process (API or worker) may `enqueue`; only workers `claim`.
- Handlers: `HANDLERS: dict[str, Callable[[Task, WorkerCtx], Awaitable[dict]]]` in `acquisition/worker/handlers.py`;
  an unknown kind → `dead` with error "no handler".
- Every handler is idempotent for its dedupe key and checks its budget before spending (`BudgetGuard.charge(kind, eur)`
  → raises `BudgetExceeded`, the task completes with `result={"skipped": "budget"}`).

## Schedule (`config/acquisition.yaml: schedule`)

| Kind | When | Dedupe key | Budget |
|---|---|---|---|
| `metrics_snapshot` | every 60 s | `snap:<YYYY-MM-DDTHH:MM>` | — |
| `prefetch` | hourly 06–22 UTC | `prefetch:<date>T<hour>` | `prefetch.eur_per_day` |
| `rollup` | daily 02:00 | `rollup:<date>` | — |
| `drift` | daily 02:30 (after rollup) | `drift:<date>` | — |
| `registry_review` | daily 03:00 (+ early on N attempts) | `review:<date>` | `registry.discovery.eur_per_day` |
| `insight_run` | as spec 010 (daily + early) | `insight:<date>[:early<n>]` | `insight.budget_eur` |
| `evaluator` | daily 04:00 | `eval:<date>` | — |
| `gold_load` | daily 05:00 per due dataset | `gold:<dataset>:<date>` | — |
| `retention_snapshots` | daily 01:00 | `snapret:<date>` | — |
| `baseline` | daily while a baseline window is open | `baseline:<name>:<date>` | — |
| `scout`, `rule_auditor`, `extractor_tuner` | daily 03:30 | `<agent>:<date>` | `agents.budgets.<agent>` |
| `parser_doctor` | on drift/zero streak | `doctor:<version_key>` | `agents.budgets.parser_doctor` |
| `gate_replay`, `gate_shadow`, `watch` | on change state | `<gate>:<change_id>[:<day>]` | the change's agent budget |
| `blame_judge` | on disputed blame | `blame:<signal_id>` | `agents.budgets.blame_judge` |

## Metrics (worker exporter, `:9101/metrics`)

`automind_worker_beat_timestamp_seconds`, `automind_acq_tasks{kind,state}` (gauge from the table each minute),
`automind_acq_task_duration_seconds{kind}` (histogram), `automind_acq_task_failures_total{kind}`,
`automind_background_spend_today_eur{loop}` (moved from the app), plus every 010 snapshot gauge (moved with
`metrics_snapshot`). New rule `WorkerDown`: `time() - automind_worker_beat_timestamp_seconds > 120` for 2 m.
