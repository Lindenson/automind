"""Chat · chat.domain.identification: when a car counts as identified, and which exact version it is.

Owns: `identification` — `settled` (research never starts on an unsettled car), answer checks, equipment level;
  `ladder` — narrowing a car over the versions sold in its generation: engine → gearbox → driven wheels;
  `used` — a used car's assumed age, sourced used price and warranty status;
  `variant_match` — does a catalogued version fit the car (generation, gearbox, drive, engine, level), the same
  model under another spelling, the order of fitting rows;
  `rejection` — what the person rejected (`Rejection`, `RejectLevel`) and `exclude_rejected`, the one filter of
  every candidate pool (spec 013 I3); `verify` — a candidate checked against the person's words (I2);
  `tactic` — after a rejection, a dead end or a repeated question widens the search (T024).
Flow: versions of the generation (application) → `ladder.narrow` → `ladder.next_step` asks one level →
  `ladder.decide` → `identification.settled`; every pool through `rejection.exclude_rejected`, a version found
  through `verify`, the outcome through `tactic`.
Depends on: chat.domain.case, shared.vehicle.identity, shared.evidence.sense, rapidfuzz (`variant_match`).
Must not depend on: sqlalchemy, langgraph, fastapi, chat.application, chat.dialog.
Note: `used` is also imported by acquisition.pipeline.persist (shared knowledge, not chat-only).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["identification", "ladder", "rejection", "tactic", "used", "variant_match", "verify"]
