"""Shared · shared.text: building text patterns that depend on a word known only at run time.

Owns: `patterns` — `whole_word(word)`: the compiled "this word, not part of a longer one" pattern (cached).
Depends on: the standard library. Must not depend on: any area.
Public API: the modules in __all__.
"""

__all__ = ["patterns"]
