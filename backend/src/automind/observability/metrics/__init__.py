"""Observability · automind.observability.metrics: the slow Prometheus values computed from the journals.

Owns: `snapshot` — KPIs, source scores and loop health, recomputed from the journals every minute and served by the
  `SnapshotCollector` of shared.infrastructure.metrics.prom.
Flow: the worker refreshes `snapshot`; delivery.web.metrics and the worker exporter serve the scrape from memory,
  never from the database (FR-031). Live counters and the loop heartbeat live in shared.infrastructure.metrics.
Depends on: prometheus_client, shared.infrastructure (config, db, metrics). Must not depend on: delivery.
Note: `snapshot` reads chat.infrastructure and acquisition.parsing lazily (it analyses both cycles).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["snapshot"]
