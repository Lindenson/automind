"""Patterns built from a word at run time. Fixed patterns live as named constants in the module that uses them (or a
vocabulary module); a pattern that depends on a word — a make, a region name, an engine family — is built here,
once per word (cached, as `re` caches compiled patterns)."""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=4096)
def whole_word(word: str, *, hyphen_inside: bool = False, ignore_case: bool = False) -> re.Pattern[str]:
    """`word` as a whole word: "tsi" in "1.5 tsi" but not in "etsi" (`hyphen_inside`: a hyphen counts as part of a
    word, so "tsi" is not found in "e-tsi" either)."""
    edge = r"[\w-]" if hyphen_inside else r"[\w]"
    return re.compile(rf"(?<!{edge}){re.escape(word)}(?!{edge})", re.I if ignore_case else 0)


@lru_cache(maxsize=256)
def word_after_any(names: str) -> re.Pattern[str]:
    """One of `names` (a regex alternation), its spaces, then the next word: "Li L9" in "lixiang L9 Max" →
    group 1 "lixiang ", group 2 "L9" (case-insensitive)."""
    return re.compile(rf"(?i)((?<!\w)(?:{names})\s+)([^\s,.;:!?»«]+)")
