"""Whose car the words are about: "my" / "моего" / "mi" mark the person's own car, and "to replace" / "вместо" /
"en lugar de" say the purchase replaces it (009 FR-022, chat 20b5b7f9: "find me a Kia to replace my Prado 150")."""

from __future__ import annotations

import re

# "для замены моего", "вместо", "to replace my", "instead of", "para sustituir", "en lugar de"
_REPLACING = re.compile(r"замен|вместо|на смену|replac|instead of|sustitu|reemplaz|en lugar de|cambiar mi", re.I)
# "мой", "моего", "my", "mine", "mi", "mis" as whole words
_OWN = re.compile(r"(?<!\w)(мо[йеёюяи]\w*|my|mine|mi|mis)(?!\w)", re.I)


def replaces_a_car(text: str) -> bool:
    """The words say the purchase replaces a car ("to replace my Prado", "вместо моего")."""
    return bool(_REPLACING.search(text))


def says_own(text: str) -> bool:
    """The words contain "my" in some language ("my Toyota" is the person's own car)."""
    return bool(_OWN.search(text))


def is_own_word(word: str) -> bool:
    """The word itself is "my" / "моего" / "mi" (a make right after it is the person's own car)."""
    return bool(_OWN.fullmatch(word))
