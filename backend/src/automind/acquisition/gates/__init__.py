"""Acquisition · acquisition.gates: the gates every agent change passes before it is live, and its journal.

Owns:
  `domain` — the `Change` record and its rules; a relevance keyword change's measure (the verdicts are
    `acquisition.domain.gates` and `relevance_audit`).
  `application` — `ChangeJournal` (propose, advance, accept, keep, reject, abandon, rollback), `ReplayGate`,
    `ShadowGate`, `Watch`, and their ports.
  `infrastructure` — the journal's store, the candidate objects, the experiments, the measures on stored pages, the
    lever state, and `wiring` (`change_journal()`, `replay_gate()`, `shadow_gate()`, `watch()`).
Flow: journal.propose → ReplayGate → ShadowGate → journal.accept → Watch (→ rollback); old and new versions measured
  on the same stored pages, one code path with live.
Depends on: agents (levers, budget), domain, parsing, pipeline, replay, snapshots, infrastructure, worker, shared.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
Note: agents call the journal (wiring) and the journal checks proposals with `agents.levers`.
"""

__all__: list[str] = ["application", "domain", "infrastructure"]
