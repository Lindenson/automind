"""Chat · chat.infrastructure.persistence: repositories over the conversation tables; one short session per call.

Owns: `repositories` — ChatRepo, CaseRepo, TurnRepo, EventRepo, JobRepo, MessageRepo, MetricsRepo,
  FeasibilityRepo, MarketFactRepo, RatingRepo, ModelVersionsRepo (they implement chat.application.ports).
Depends on: shared.infrastructure.db, chat.application.ports, chat.domain, sqlalchemy.
Must not depend on: chat.dialog, delivery.web.
Note: MetricsRepo and MarketFactRepo serve acquisition / observability too; one module per aggregate and
  per-area persistence in S12 (T057).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["repositories"]
