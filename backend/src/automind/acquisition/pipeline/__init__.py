"""Acquisition · acquisition.pipeline: one research job — one car × one area — from search to stored values.

Owns:
  `job` — run_job, the whole path; `plan` — what to search; `searches` — one job's whole search;
  `locate` — search (cache-first) and rank; `fetch` — the ranked URLs through the page store;
  `relevance` — is a page about the job's car; `parse` — deterministic site readers; `extract` — extraction
  schemas and model calls for other pages; `validate` — checks every value passes; `persist` — a page's evidence
  and rows; `stamp` — who produced a claim (page, producer, version, model); `identity` — identity readers
  (lineup, versions); `market` — market-level incentives as stored.
  `domain/` — records (variant, rows) and pure rules (area items, value selection, hits);
  `application/` — the stores' ports (`PipelineStores`, `PipelineStoreUnavailable`) and `ValueSelection` (merge);
  `infrastructure/` — every SQL of the pipeline (stores) and `wiring` (`stores()`, `value_selection()`).
Flow: plan → searches (locate → fetch) → relevance → parse or extract → validate → persist → merge
  (then area freshness and section minimum; each page is a registry attempt).
Depends on: api (contracts), read, ports, domain, gates, registry.api, infrastructure, chat.domain, shared
  (contracts, evidence, vehicle, research_order, metering); pydantic; the stores on shared.infrastructure.db.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); started by facade and the worker's prefetch.
Note: the pipeline imports the chat's domain (intake, identification.used); `market` stores incentives, not a stage;
  job.py uses read's private `_have`.
"""

__all__: list[str] = [
    "application",
    "domain",
    "extract",
    "fetch",
    "identity",
    "job",
    "locate",
    "infrastructure",
    "market",
    "parse",
    "persist",
    "plan",
    "relevance",
    "searches",
    "stamp",
    "validate",
]
