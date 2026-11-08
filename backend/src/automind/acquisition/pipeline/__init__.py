"""Acquisition · acquisition.pipeline: one research job — one car × one area — from search to stored values.

Owns:
  `job` — `ResearchJob`, whose `run()` lists the stages; `contracts` — JobSpec, JobResult, Emit, Found, PageTally;
  `scope` — what the running job knows (the registry's plan, its candidates; "unverified" pages);
  `stages/` — opening, car_pages, market_pages, book (the named stages `run()` calls);
  `plan` — what to search; `home_market` — a car sold only outside Europe; `searches` — one job's whole search;
  `locate` — search (cache-first) and rank; `fetch` — the ranked URLs through the page store;
  `relevance` — is a page about the job's car; `parse` — deterministic site readers; `extract` — extraction
  schemas and model calls for other pages; `validate` — checks every value passes; `persist` — a page's evidence
  and rows; `stamp` — who produced a claim (page, producer, version, model); `identity` — identity readers
  (lineup, versions); `market` — market-level incentives as stored.
  `domain/` — records (variant, rows, target, critical values) and pure rules (area items, value selection, hits);
  `application/` — the stores' ports (`PipelineStores`, `PipelineStoreUnavailable`) and `ValueSelection` (merge);
  `infrastructure/` — every SQL of the pipeline (stores) and `wiring` (`stores()`, `value_selection()`).
Flow: opening → plan → searches (locate → fetch) → relevance → parse or extract → validate → persist → merge →
  book (registry attempts, shadow feed, the area's hits, minimum and run, the job's metrics).
Depends on: api (contracts), ports (`AcqPorts`, incl. the shadow gate's feed), domain, registry.api,
  infrastructure (overrides), chat.domain, shared (contracts, evidence, vehicle, research_order, metering);
  pydantic; the stores on shared.infrastructure.db.
Must not depend on: as acquisition/__init__ (registry-no-chat); gates, agents, worker, delivery
  (pipeline-knows-no-gates).
Public API: the modules in __all__ (callers import from them); started by facade and the worker's prefetch.
Note: the pipeline imports the chat's domain (identification.used).
"""

__all__: list[str] = [
    "application",
    "contracts",
    "domain",
    "extract",
    "fetch",
    "home_market",
    "identity",
    "job",
    "locate",
    "infrastructure",
    "market",
    "parse",
    "persist",
    "plan",
    "relevance",
    "scope",
    "searches",
    "stages",
    "stamp",
    "validate",
]
