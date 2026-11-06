"""Versioned prompts (*.md). Loaded once and passed to the application via `Reference.prompts`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent


@lru_cache
def load_all() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8").strip() for p in sorted(DIR.glob("*.md"))}
