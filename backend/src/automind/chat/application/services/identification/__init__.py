"""Chat · chat.application.services.identification: finds out which exact car (make, model, version) is meant.

Owns: `service` — `IdentificationService`: `run()` identifies one car through named stages, `identify_case()` every
  changed car of a case; `contracts` — the request, the `Fallback` protocol, the resolver's `VariantIdentity`, the
  reasons it gives up; `stages/` — normalise_name, catalogue_lookup, ask_model, place_market, year_first,
  narrow_ladder, ask_stale_version, offer_engines, settle; `strategies/` — the fallbacks in order: sourced_versions,
  catalogue_rows, open_world; `resolver` — the LLM resolver with sources; `catalogue` — the catalogue as
  identification uses it (over acquisition.api); `assessment` — a car looked up in the catalogue for the policy;
  `revalidation` — a version set earlier checked again; `versions` — versions of a generation with sources;
  `lineup` — a make's models on a market; `candidates` — candidate cars when no model is named.
Flow: normalise_name → catalogue_lookup → (ask_model) → place_market → year_first → sourced_versions →
  catalogue_rows → open_world → settle (outcome IDENTIFIED / CHOICES / NEED / NOT_FOUND recorded on the car).
Depends on: chat.domain (identification.ladder, identification.variant_match), chat.application.ports,
  acquisition.api, shared.evidence, shared.vehicle.
Must not depend on: chat.dialog, delivery.web, langgraph, the database.
Public API: the names in __all__; the other modules are imported by path where their concept is needed.
"""

from automind.chat.application.services.identification.contracts import IdentifyRequest
from automind.chat.application.services.identification.service import CaseIdentified, IdentificationService

__all__ = ["CaseIdentified", "IdentificationService", "IdentifyRequest"]
