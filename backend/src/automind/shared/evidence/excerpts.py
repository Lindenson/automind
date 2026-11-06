"""Verbatim excerpts: does a quoted excerpt occur in the page (markup and short ellipses tolerated) and does it contain
the claimed value (constitution I; FR-030)."""

from __future__ import annotations

import re
import unicodedata

_MARKUP = re.compile(r"\\(?=[*_#|\\`\[\]()-])|[*#|`]+|(?<!\w)_+|_+(?!\w)")


_GAP = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")


def _norm(text: str) -> str:
    """Text for literal comparison: Unicode-normalised, lower case, without markdown markup (bold, headings,
    table pipes, escapes) and with collapsed whitespace. Page text is stored as markdown; models quote the
    rendered words (user report 2026-11-02: the Tucson price "**36.075 euros**" failed the excerpt check)."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = t.replace("\u00a0", " ").replace("\u202f", " ")
    t = _MARKUP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


MAX_GAP_CHARS = 200  # FR-030: an ellipsis skips a few words, never half a page


def occurs(excerpt: str, document_text: str, max_gap_chars: int = MAX_GAP_CHARS) -> bool:
    """The excerpt occurs in the document; an ellipsis in the excerpt ("Klass ... Precio") skips at most
    `max_gap_chars` of text, and the parts must occur in order (spec 007 FR-030: "Golf 1.0 TSI ... 1.500 kg"
    with the parts 6,000 characters apart is not an excerpt)."""
    doc = _norm(document_text)
    parts = [p for p in (_norm(x) for x in _GAP.split(excerpt)) if p]
    if not parts:
        return False

    def chain(k: int, pos: int) -> bool:
        if k == len(parts):
            return True
        i = doc.find(parts[k], pos)
        while i >= 0 and i - pos <= max_gap_chars:
            if chain(k + 1, i + len(parts[k])):
                return True
            i = doc.find(parts[k], i + 1)
        return False

    start = doc.find(parts[0])
    while start >= 0:
        if chain(1, start + len(parts[0])):
            return True
        start = doc.find(parts[0], start + 1)
    return False


def _number_in(number: str, text: str) -> bool:
    """The number occurs as a whole number (FR-031: "150" is not in "1500 rpm", nor "1,5" in "11,5")."""
    return re.search(rf"(?<![\d.,]){re.escape(number)}(?![\d]|[.,]\d)", text) is not None


def validate_excerpt(excerpt: str, raw_value: str, document_text: str) -> bool:
    """The excerpt must literally occur in the document, and the raw value inside the excerpt."""
    ex = _norm(excerpt)
    if len(ex) < 4:
        return False
    if not occurs(excerpt, document_text):
        return False
    val = _norm(raw_value)
    if re.search(r"\d", val) is None and val in ex:
        return True
    digits = re.findall(r"\d+(?:[.,]\d+)*", val)  # "44.250,00" is one number
    return bool(digits) and all(_number_in(d, ex) for d in digits)
