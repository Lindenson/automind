"""Shared · shared.provenance: who produced a value — the version keys of readers, prompts, models and parser specs,
and the record of which model and prompt version actually answered a call.

Owns: `versions` — version identifiers (reader@v, prompt hash, model) and their parsing; `served` — the served-call
  record (a contextvar the LLM gateway fills and the engine's stamp reads).
Depends on: nothing outside the standard library. Must not depend on: chat, acquisition, observability, delivery.
Public API: the modules in __all__.
"""

__all__ = ["served", "versions"]
