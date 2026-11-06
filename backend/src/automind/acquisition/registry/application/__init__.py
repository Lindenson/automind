"""Acquisition · acquisition.registry.application: the registry's use cases behind its port.

Owns:
  `service` — RegistryService: the port's use cases (plan, attempts, signals); never raises into research.
  `admission` — sites met in searches checked before any use, and re-checked every 90 / 180 days.
  `review` — the daily review: fade, rescore, move statuses, journal every change (only with autonomy on).
  `seed` — seed the registry from favourites and the 009 survey (idempotent).
Depends on: registry.api, registry.domain, registry.infrastructure, acquisition.domain, shared (infrastructure.db,
  config), observability.metrics; sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); delivery.web.app uses only `seed`.
"""

__all__: list[str] = ["admission", "review", "seed", "service"]
