"""Text as the excerpt checks compare it: NFKC-folded, lowercased, no-break spaces and whitespace runs as one space."""

from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def folded(text: str) -> str:
    """ "Potencia  MÁXIMA " → "potencia máxima"."""
    t = unicodedata.normalize("NFKC", text).lower().replace(" ", " ")
    return _SPACES.sub(" ", t).strip()
