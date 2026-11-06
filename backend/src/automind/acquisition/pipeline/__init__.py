"""Acquisition · acquisition.pipeline: one research job — one car × one area — from search to stored values.

Owns:
  `job` — run_job, the whole path; `plan` — what to search; `locate` — search (cache-first) and rank.
  `fetch` — the ranked URLs through the page store; `relevance` — is a page about the job's car.
  `parse` — deterministic site readers; `extract` — extraction schemas and model calls for other pages.
  `validate` — checks every value passes; `persist` — store evidence and claims; `merge` — selected values.
  `stamp` — who produced a claim (page, producer, version, model); `identity` — identity readers (lineup, versions).
  `market` — market-level incentives as stored.
Flow: plan → locate → fetch → relevance → parse or extract → validate → persist → merge
  (then area freshness and section minimum; each page is a registry attempt).
Depends on: api (contracts), read, ports, domain, gates, registry.api, infrastructure, chat.domain, shared
  (contracts, evidence, vehicle, research_order, infrastructure, metering); pydantic, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); started by facade and the worker's prefetch.
Note: the pipeline imports the chat's domain (intake, identification.used); `market` stores incentives, not a stage;
  job.py uses read's private `_have`.
"""

__all__: list[str] = [
    "extract",
    "fetch",
    "identity",
    "job",
    "locate",
    "market",
    "merge",
    "parse",
    "persist",
    "plan",
    "relevance",
    "stamp",
    "validate",
]
