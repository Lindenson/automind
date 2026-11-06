"""Observability · automind.observability: sees how both cycles do: turn outcomes, metrics, the insight loop.

Owns:
- `domain` — pure rules: turn outcome score, failure grouping, impact, config levers, the "copy for Claude Code" text.
- `application` — one analysis run (failures → issues → diagnoses) and the seed issues.
- `infrastructure` — turn outcomes and feedback (`OutcomeRepo`), failures from the journals and the issue table.
- `metrics` — Prometheus metrics: live counters, the slow-value snapshot, loop heartbeats.
- `loop` — the insight loop: daily or when failures pile up; run by the acquisition worker, never in the API.
- `prompts/` — the analyst's prompt (analyst_issue.md); data, not a package.
Flow: chat turns end → `OutcomeRepo` stores the outcome → `loop` reads failures → `application.analyse` groups them
into issues with diagnoses (advice only: no code, rule or config is changed) → delivery.web.admin shows them.
Depends on: shared (infrastructure.config, infrastructure.db, infrastructure.llm). Must not depend on: chat.dialog,
chat.application, delivery, acquisition internals (target `observability-reads-only`).
Must be imported by nobody but delivery (target `observability-is-a-leaf`, spec review B2).
Note: not yet a leaf — `metrics` (prom, heartbeat) is imported across chat, acquisition and shared; chat adapters build
the `OutcomeRepo` and the worker runs `loop` and the snapshot (composition moves in S10/S12); `loop` and
`metrics.snapshot` read chat.infrastructure and acquisition.parsing.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["application", "domain", "infrastructure", "loop", "metrics"]
