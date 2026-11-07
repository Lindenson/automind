"""Acquisition · acquisition.gates.domain: pure rules of the change journal and the gates.

Owns: `change` — the `Change` record and its rules (explanation, gate results, corpus window, version text);
  `relevance_change` — a relevance keyword change: keyword lists, references, the measure of re-judged pages.
  The verdicts themselves are `acquisition.domain.gates` and `acquisition.domain.relevance_audit`.
Must not depend on: storage, the network, the application layer.
Public API: the modules in __all__.
"""

__all__ = ["change", "relevance_change"]
