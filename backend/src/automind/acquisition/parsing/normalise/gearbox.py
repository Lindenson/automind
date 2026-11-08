"""The gearbox a variant name states ("… 6AT", "… manual", "… e-CVT"), used when the variant's gearbox column is
empty."""

from __future__ import annotations

import re

from automind.shared.evidence import sense

AUTOMATIC = re.compile(r"\b\d\s?(at|a/t)\b|automatic|automático|automatica")  # "8AT", "6 a/t", "automático"
MANUAL = re.compile(r"\b\d\s?(mt|m/t)\b")  # "6MT", "5 m/t"


def gearbox_in_name(variant_name: str) -> str | None:
    """ "automatic", "manual", a gearbox family ("e-CVT", "DCT", …) or None when the name says nothing."""
    name = f" {variant_name} ".lower()
    if AUTOMATIC.search(name):
        return "automatic"
    if MANUAL.search(name) or sense.says_manual(name):
        return "manual"
    return sense.gearbox_family(name)
