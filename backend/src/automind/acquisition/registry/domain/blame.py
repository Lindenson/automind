"""Who was wrong when a shown value was wrong (spec 010 FR-017, research R9). Pure.

If the stored excerpt holds the corrected value, the page said the right thing and our reading was wrong: blame the
site reader (parser) or the model extraction, never the source. Otherwise the source said the wrong thing.
"""

from __future__ import annotations

import re

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _numbers(text: str) -> set[float]:
    out: set[float] = set()
    for raw in _NUM.findall(text):
        for cand in (raw.replace(".", "").replace(",", "."), raw.replace(",", ""), raw.replace(",", ".")):
            try:
                out.add(float(cand))
            except ValueError:
                continue
    return out


def blame(corrected: str | None, excerpt: str | None, extracted_by: str | None) -> str:
    if not corrected or not excerpt:
        return "source"
    want = _numbers(corrected)
    if want and want & _numbers(excerpt):
        return "parser" if (extracted_by or "").upper() == "READER" else "extractor"
    return "source"
