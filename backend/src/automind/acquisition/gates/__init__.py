"""Acquisition · acquisition.gates: the gates every agent change passes before it is live, and its journal.

Owns:
  `journal` — the change journal (`acq_changes`) and the candidate objects: propose, advance, accept, reject, rollback.
  `evaluate` — old vs new version of a change on the same stored pages: the shared measurement.
  `replay_gate` — the replay gate on stored pages + gold; `relevance_replay` — the same for relevance keywords.
  `shadow` — both versions on the next live pages, the user sees the old one's values.
  `watch` — after acceptance: live metrics vs the accepted ones; rollback on degradation.
Flow: journal.propose → replay_gate → shadow → journal.accept → watch (→ rollback); verdicts from domain.gates.
Depends on: agents (levers), domain, parsing, pipeline, replay, snapshots, infrastructure, worker, shared
  (infrastructure.db, config, llm, contracts, evidence); pydantic, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
Note: gates and agents import each other (journal → agents.levers, agents → gates); journal.py is over 500 lines.
"""

__all__: list[str] = ["evaluate", "journal", "relevance_replay", "replay_gate", "shadow", "watch"]
