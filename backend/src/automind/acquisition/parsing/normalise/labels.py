"""Labels of a spec table as the readers compare them (spec 003 R6): lowercased, ":" removed, whitespace collapsed."""

from __future__ import annotations


def norm_label(label: str) -> str:
    """ "Potencia máxima:" → "potencia máxima" (as the v1 readers matched labels)."""
    return " ".join(label.lower().replace(":", " ").split())
