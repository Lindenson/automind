# Contract: Research Event Stream (SSE)

**Endpoint**: `GET /api/v1/researches/{id}/events` with `Accept: text/event-stream`
**Requirements**: FR-032, Story 4 scenarios 1–2, SC-010; research.md R10

## Wire format

```text
id: 42
event: task.updated
data: {"research_id":"…","seq":42,"ts":"2026-11-01T12:00:03Z","payload":{…}}

```

- `id` is the per-research monotonically increasing `seq`, which is also stored in
  `research_events`.
- **Reconnect**: the client sends `Last-Event-ID: <seq>`. The server first replays all stored
  events with `seq > Last-Event-ID` in order, then streams live events. Without the header, the
  server replays from `seq = 0`.
- A `: heartbeat` comment is sent every 15 s.
- The stream closes after a terminal event (`research.completed`, `research.failed`,
  `research.cancelled`) has been delivered.
- Payloads are API DTOs (same shapes as `openapi.yaml`). They never include graph state, prompts,
  or model reasoning (constitution V; FR-032).

## Event types

| `event` | When | `payload` |
|---|---|---|
| `research.state_changed` | Every lifecycle transition | `{from, to}` (`ResearchState`) |
| `plan.ready` | Plan built; awaiting approval | `ResearchPlan` |
| `task.updated` | Task created or its status changed | `ResearchTask` |
| `claim.progress` | At most once every 2 s per task | `{task_id, claims_accepted, claims_rejected}` |
| `conflict.detected` | Verification found a conflict | `Conflict` (status may still change) |
| `conflict.resolved` | A follow-up resolved a conflict | `Conflict` |
| `followup.started` | Follow-up round begins | `{round, max_rounds, task_count}` |
| `limit.reached` | A budget or limit was hit | `{limit, value}` |
| `usage.updated` | At most once every 5 s | `Usage` |
| `simulation.completed` | Default race finished | `SimulationSummary` |
| `research.completed` | Report stored | `{report_url}` |
| `research.failed` | Unrecoverable error | `{reason}` |
| `research.cancelled` | Cancel finished | `{partial_report_url}` |

## Client obligations (frontend)

- Validate every `data` payload with the matching Zod schema and ignore unknown event types
  (forward compatibility).
- After a reconnect fails (3 attempts with backoff), fall back to polling
  `GET /researches/{id}` every 5 s.
- Treat `GET /researches/{id}` as the source of truth. Events are deltas.
