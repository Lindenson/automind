"""Shared · shared.vehicle.specs: the specification attribute registry and the normalisation of raw values.

Owns: `registry` — every attribute (key, category, kind, canonical unit, tier) in `ATTRS`; `converters` — unit
  converters the registry entries use; `normalize` — a raw cell or excerpt to the canonical value of its attribute,
  drivetrain and gearbox words to their codes.
Depends on: shared.vehicle.units. Must not depend on: any area.
Public API: the names below (`from automind.shared.vehicle import specs; specs.normalize(...)`).
"""

from automind.shared.vehicle.specs import converters
from automind.shared.vehicle.specs.normalize import (
    DRIVETRAINS,
    RANGE_RE,
    normalize,
    normalize_drivetrain,
    normalize_transmission,
)
from automind.shared.vehicle.specs.registry import (
    ATTRS,
    Attr,
    Category,
    Kind,
)

__all__ = [
    "ATTRS",
    "Attr",
    "Category",
    "DRIVETRAINS",
    "Kind",
    "RANGE_RE",
    "normalize",
    "normalize_drivetrain",
    "normalize_transmission",
    "converters",
]
