"""The fuel of a car from its variant name (spec 003): "electric" for a BEV, "diesel" when the name carries a diesel
mark ("320d", "2.0 TDI", "E 220 d", "BlueHDi"), "petrol" otherwise."""

from __future__ import annotations

import re

DIESEL_MARKS = (" d ", "tdi", "dci", "cdi", "d-4d", "hdi", "crdi", "diesel", "jtd", "multijet", "tdci", "bluehdi",
                "skyactiv-d", "i-dtec", "ecoblue")  # fmt: skip
DIESEL_SUFFIX = re.compile(r"\b\d{3}d\b|\b\d\.\dd\b|\b\d{3} d\b")  # 520d, 2.0d, E 220 d


def fuel_of(variant_name: str, powertrain: str | None) -> str | None:
    """ "electric", "diesel" or "petrol" for a variant named `variant_name` with this powertrain."""
    if (powertrain or "").upper() == "BEV":
        return "electric"
    n = f" {variant_name.lower()} "
    if any(k in n for k in DIESEL_MARKS) or DIESEL_SUFFIX.search(n) is not None:
        return "diesel"
    return "petrol"
