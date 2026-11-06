"""Shared · shared.infrastructure.metrics: Prometheus instrumentation every area increments (counters, histograms)
and the in-memory health of background loops. The analysis of these numbers is observability's job.

Owns: `prom` — the metric definitions and their helpers; `heartbeat` — last-run times of the background loops.
Depends on: prometheus_client. Must not depend on: chat, acquisition, observability, delivery.
Public API: the modules in __all__.
"""

__all__ = ["heartbeat", "prom"]
