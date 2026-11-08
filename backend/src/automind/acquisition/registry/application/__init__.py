"""Acquisition · acquisition.registry.application: the registry's services behind its ports.

Owns:
  `ports` — the stores and collaborators the services need; one `RegistryStoreUnavailable`.
  `service` — RegistryService: the port's use cases (plan, `site:` sources, attempts, signals); never raises into
    research.
  `admission` — SiteAdmission: sites met in searches checked before any use, and re-checked every 90 / 180 days.
  `review` — DailyReview: fade, rescore, move statuses, journal every change (only with autonomy on).
  `seed` — RegistrySeed: the registry seeded from favourites and the 009 survey (idempotent).
Flow: registry.infrastructure.wiring builds each service over the stores; the rules are in registry.domain.
Depends on: registry.api, registry.domain, acquisition.domain.
Must not depend on: registry.infrastructure, sqlalchemy, shared.infrastructure.db (storage only through the ports);
  as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["admission", "ports", "review", "seed", "service"]
