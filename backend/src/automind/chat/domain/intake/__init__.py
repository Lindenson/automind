"""Chat · chat.domain.intake: the intake loop — what to ask next about a car, and reading facts out of free text.

Owns: `intake` — `next_step` (ASK / PROPOSE / …), progress and repeat checks, identity keys, line-up ranking and
  candidate picking, and text parsers (condition, region, distance, charging, electricity price, energy figures).
Depends on: chat.domain.case, shared.vehicle.identity. Must not depend on: sqlalchemy, langgraph, fastapi,
  chat.application, chat.dialog.
Note: one 786-line module mixes the step machine, ranking and text parsers; split in S5 (T049: step machine →
  dialog, parsers → domain.understanding, markets → shared.vehicle). acquisition.pipeline also imports it.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["intake"]
