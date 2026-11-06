"""Observability · automind.observability.metrics: Prometheus metrics of both cycles and the health of their loops.

Owns:
- `prom` — the metric families: live counters/histograms (`inc`, `observe_turn`, `add_cost`) and the
  `SnapshotCollector` that serves the last `Snapshot`.
- `snapshot` — the slow values (KPIs, source scores, loop health), recomputed from the journals every minute.
- `heartbeat` — in-memory health of the background loops (`register`, `beat`), exported to Prometheus.
Flow: code increments `prom` where things happen; the worker refreshes `snapshot`; delivery.web.metrics and the
worker exporter serve the scrape from memory, never from the database (FR-031).
Depends on: prometheus_client, shared.infrastructure (config, db, llm). Must not depend on: delivery.
Note: `prom` and `heartbeat` are imported across chat, acquisition and shared (not yet a leaf); `snapshot` reads
chat.infrastructure and acquisition.parsing lazily.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["heartbeat", "prom", "snapshot"]
