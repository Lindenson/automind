"""Acquisition · acquisition.replay: offline replay of a reader or extractor version over stored pages, scored on gold.

Owns:
  `run` — the replay itself: resolve the reader, read stored pages, compare with gold (domain.replay), report.
  `offline` — the no-network guard while readers run.
  `command` — the replay command (arguments, report), run by `python -m automind.cli replay`.
Flow: stored pages (snapshots) → reader/extractor version (under offline.no_network) → validate → compare with gold.
Depends on: domain, gold, parsing, pipeline, snapshots, infrastructure, chat.infrastructure (LiveLLM, extractor
  replay only), shared (infrastructure, contracts, evidence, vehicle); pydantic, sqlalchemy.
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them); used by the gates, the parser doctor and the CLI.
"""

__all__: list[str] = ["command", "offline", "run"]
