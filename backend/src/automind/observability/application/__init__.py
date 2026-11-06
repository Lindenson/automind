"""Observability · automind.observability.application: one insight analysis run, and the known flaws as seed issues.

Owns:
- `analyse` — `run_once`: failures → groups → issues → diagnoses within the daily budget; ports `Repo`, `LLM`.
- `seed` — `seed_issues`: the issues from config/seed_issues.yaml, idempotent by slug.
Flow: `loop` gives `run_once` the failures, a repo and a model → `domain.clusters.group` → `domain.impact` →
the model diagnoses each new issue → `domain.levers.check_fix` vets the proposed fix → the issue is saved.
Side effects only on `insight_issues` and `insight_runs` (FR-010).
Depends on: observability.domain, shared.infrastructure (config, db). Must not depend on: chat, acquisition,
delivery.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["analyse", "seed"]
