"""Chat · chat.application.services.identification: finds out which exact car (make, model, version) is meant.

Owns: `identify` — the identify step per car: make registry → known models → catalog fit → resolver;
  `resolve` — catalog variant lookup and LLM resolver with sources; `versions` — versions of a generation sold in
  Spain (cache-first, else acquisition search); `lineup` — a make's models on sale in Spain (cache-first);
  `candidates` — candidate cars when no model is named.
Flow: `identify.identify_car` → `resolve.assess_car` (catalog) → `versions.lookup` → domain ladder narrows →
  outcome IDENTIFIED / CHOICES / … recorded on the case.
Depends on: chat.domain, chat.application.ports, acquisition.api, shared.evidence, shared.vehicle.
Must not depend on: chat.dialog, delivery.web, langgraph.
Note: `resolve` and `lineup` still query the DB with sqlalchemy (.importlinter exceptions); `identify` (724 lines)
  and `resolve` (646) become a service with stages and strategies in S7.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["candidates", "identify", "lineup", "resolve", "versions"]
