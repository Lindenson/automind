"""Chat · chat.domain.identification: when a car counts as identified, and which exact version it is.

Owns: `identification` — `settled` (research never starts on an unsettled car), answer checks, equipment level;
  `ladder` — narrowing a car over the versions sold in its generation: engine → gearbox → driven wheels;
  `used` — a used car's assumed age, sourced used price and warranty status.
Flow: versions of the generation (application) → `ladder.narrow` → `ladder.next_step` asks one level →
  `ladder.decide` → `identification.settled`.
Depends on: chat.domain.case, shared.vehicle.identity. Must not depend on: sqlalchemy, langgraph, fastapi,
  chat.application, chat.dialog.
Note: `used` is also imported by acquisition.pipeline.persist (shared knowledge, not chat-only).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["identification", "ladder", "used"]
