"""Shared · automind.shared.contracts: protocols and value types the chat and the engine both use.

Owns:
- `config` — `Reference`: static reference data from config/*.yaml, built by infrastructure, passed to both areas.
- `json` — `JsonObject`: a JSON document at the edge (UI blocks, event payloads), the one sanctioned loose type.
- `llm` — `LLM`: model access per role (the protocol; shared.infrastructure.llm.gateway implements it).
- `web` — `WebDoc`, `SearchHit`, `Page` and the `SearchProvider` / `Searcher` / `PageStore` protocols.
- `site_readers` — `SiteReading` rows from a known site's page and the `SiteReaders` protocol.
Depends on: shared.vehicle (types used in `Reference`). Must not depend on: chat, acquisition, observability,
delivery, shared.infrastructure (contracts are declarations; implementations live elsewhere).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["config", "json", "llm", "site_readers", "web"]
