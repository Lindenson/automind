"""Acquisition · acquisition.pipeline.stages: the named stages of one research job, in the order `job.ResearchJob`
runs them.

Owns:
  `opening` — the job's scope: gated overrides refreshed, the registry's plan, the context the other stages read;
  `car_pages` — a car area's pages: relevance → table reader or extraction → checked rows stored;
  `market_pages` — a market area's pages: extraction → facts stored once per market and key;
  `book` — after reading: the registry attempts, the shadow gate's feed, the area's hits, minimum and run, the job's
  metrics.
Flow: opening → (searches) → car_pages | market_pages → book.
Depends on: the pipeline's modules and ports (`AcqPorts`), registry.api, infrastructure.overrides, shared.
Must not depend on: chat, delivery.
Public API: the modules in __all__ (`job.py` calls them).
"""

__all__: list[str] = ["book", "car_pages", "market_pages", "opening"]
