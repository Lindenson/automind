"""S5 validate (spec 011 strangler, research R5): the checks every value passes before it is stored — the verbatim
excerpt, the unit layer, plausibility, the meaning ("sense") rules and the validator role. Moved from
`application/research.py` with the bodies unchanged; S4 moved the variant's fuel and gearbox first (relevance uses
them).
"""

from __future__ import annotations

import re

from automind.domain import sense
from automind.infrastructure import db

VERSION = "validate@1"


def fuel_of(variant_name: str, powertrain: str | None) -> str | None:
    if (powertrain or "").upper() == "BEV":
        return "electric"
    n = f" {variant_name.lower()} "
    diesel = (" d ", "tdi", "dci", "cdi", "d-4d", "hdi", "crdi", "diesel", "jtd", "multijet", "tdci", "bluehdi",
              "skyactiv-d", "i-dtec", "ecoblue")  # fmt: skip
    if any(k in n for k in diesel) or re_diesel_suffix(n):
        return "diesel"
    return "petrol"


def re_diesel_suffix(n: str) -> bool:
    return re.search(r"\b\d{3}d\b|\b\d\.\dd\b|\b\d{3} d\b", n) is not None  # 520d, 2.0d, E 220 d


def _variant_gearbox(v: db.Variant) -> str | None:
    """The gearbox named in the variant name ("… 6AT", "… manual", "… e-CVT"), when the column is empty."""
    name = f" {v.variant_name} ".lower()
    if re.search(r"\b\d\s?(at|a/t)\b|automatic|automático|automatica", name):
        return "automatic"
    if re.search(r"\b\d\s?(mt|m/t)\b", name) or sense.says_manual(name):
        return "manual"
    return sense.gearbox_family(name)
