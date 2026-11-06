"""Chat · chat.dialog.prompts: the versioned LLM prompts (*.md) and their loader.

Owns: one Markdown file per prompt (interpreter, asker, resolver, reporters per persona, answerer, extractors …);
  `load_all()` — reads every *.md once into {name: text}; the result is passed on via `Reference.prompts`.
Flow: delivery.web.app calls `load_all()` at startup → the texts reach agents and services through the reference.
Depends on: the standard library only. Must not depend on: anything in automind.
Note: it also holds the acquisition engine's prompts (scout, extract_*, query_planner, parser_doctor, rule_auditor,
  blame_judge …), not only the chat's.
Public API: the names in __all__ (callers import from them).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

__all__ = ["DIR", "load_all"]

DIR = Path(__file__).resolve().parent


@lru_cache
def load_all() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8").strip() for p in sorted(DIR.glob("*.md"))}
