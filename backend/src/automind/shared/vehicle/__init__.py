"""Shared · automind.shared.vehicle: what a car is: its exact identity, its spec attributes and their units.

Owns:
- `identity` — aliases, canonical keys, generation years, de-duplication, engine parsing (constitution II).
- `specs` — the attribute registry (Tier 1 core, practicality, Tier 2 engineering, buyer data) and normalisers.
- `units` — deterministic number and unit parsing and conversion (constitution III).
- `makes` — `MakeRegistry`: makes sold in Spain, aliases, transliterations, official sites, model matching.
Depends on: the standard library (`makes` also uses rapidfuzz). Must not depend on: chat, acquisition, observability,
delivery, shared.infrastructure (identity/specs/units are pure: import contract `domain-pure`).
Note: `identity` still imports `EngineHint` from chat.domain.case.casefile lazily (kernel debt, untangled in S4).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["identity", "makes", "specs", "units"]
