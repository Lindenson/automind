"""Acquisition · acquisition.infrastructure: the engine's I/O — config files, page fetch, page store, search, wiring.

Owns:
  `config` — the engine's YAML config files (read only).
  `fetch` — direct page fetch under the policy: deny-list → robots → rate limit → timeout → size.
  `pages` — the cache-first page store (`documents`), writes snapshots on every network fetch.
  `search` — web search providers behind a cache-first searcher.
  `overrides` — runtime overrides accepted through the gates, layered over the YAML files.
  `retention` — removal of expired search results and pages (pages backing evidence are kept).
  `wiring` — the live engine ports (AcqPorts) of this process.
Depends on: domain, parsing, ports, snapshots, identity_readers, registry, shared (infrastructure, contracts, evidence,
  research_order), observability.metrics, chat.infrastructure; sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
Note: wiring reaches into chat.infrastructure (MarketFactRepo, LiveLLM); retention is started by delivery.web.app
  (an import-linter exception until it moves to the worker in S12).
"""

__all__: list[str] = ["config", "fetch", "overrides", "pages", "retention", "search", "wiring"]
