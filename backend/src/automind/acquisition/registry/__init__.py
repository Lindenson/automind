"""Acquisition · acquisition.registry: the source registry — which sites to use for which data, and how good they are.

Owns:
  `api` — the registry port (Plan, Attempt, TruthSignalIn, RegistryPort): the only registry module the chat imports.
  `domain` — pure rules: sources, capabilities, scores, lifecycle, admission, hard limits.
  `application` — services over ports: plan and record attempts, admission of new sites, daily review, seed.
  `infrastructure` — the stores (every SQL), the terms-of-use check of a site, `wiring` (callers build services there).
  `prompts/` — prompt text of the `terms_reader` web reader (data, not code).
Flow: pipeline asks api for a plan → research reports attempts and truth signals → daily review rescores and moves.
Depends on: acquisition.domain, infrastructure (config, fetch), reputation, snapshots, shared,
  observability.metrics.
Must not depend on: as acquisition/__init__ (registry-no-chat); outside the engine only `api` (registry-boundary).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["api", "application", "domain", "infrastructure"]
