"""Shared · automind.shared.evidence: pure rules that decide whether a value from a source can be trusted.

Owns:
- `evidence` — source policy and typing, excerpt validation, provenance, conflict resolution, confidence (spec 001).
- `sense` — sense checks: is the value the right kind for its attribute (test cycle, gearbox, intervals; spec 004).
Flow: classify the source → validate the excerpt → assign provenance → `select_value` resolves conflicts;
`sense` runs next to unit normalisation and plausibility.
Depends on: shared.vehicle. Must not depend on: chat, acquisition, observability, delivery, shared.infrastructure
(pure domain: import contract `domain-pure`); policies arrive by `configure`, never by reading files.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["evidence", "sense"]
