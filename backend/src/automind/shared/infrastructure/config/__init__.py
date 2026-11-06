"""Shared · automind.shared.infrastructure.config: settings and YAML configuration, turned into plain values.

Owns:
- `settings` — `Settings` (pydantic-settings from .env: database URL, API keys, hosts, tokens) and `settings()`.
- `loader` — loaders of config/*.yaml (models, prices, aliases, policies, queries…), `Reference` assembly and
  `configure_domain`, which hands the pure domain modules their values at startup.
Flow: a composition root (web app, worker, CLI) calls `configure_domain` → the loaders read config/*.yaml →
the domain modules receive plain values, never files.
Depends on: shared.contracts, shared.evidence, shared.vehicle, pydantic-settings, PyYAML.
Must not depend on: chat, acquisition, delivery (target `shared-is-kernel`); observability.
Note: `loader` still assembles `Reference` from chat and engine modules (chat.domain criteria, chat.application
history, acquisition relevance and overrides) — untangled in S4.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["loader", "settings"]
