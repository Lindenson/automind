"""How close two values must be to count as the same: an absolute amount or a share of the reference. Pure.

Tolerances come from configuration as `("abs" | "rel", amount)` pairs (gold.yaml, replay and reputation settings).
"""

from __future__ import annotations

from enum import StrEnum

Tolerance = tuple[str, float]  # (a ToleranceKind value, amount)


class ToleranceKind(StrEnum):
    """How a tolerance's amount is read."""

    ABS = "abs"  # the amount itself, in the attribute's unit
    REL = "rel"  # a share of the reference value


EPSILON = 1e-9  # float noise


def within(value: float, reference: float, tol: Tolerance) -> bool:
    """Whether `value` is within `tol` of `reference`."""
    kind, amount = tol
    allowed = amount if kind == ToleranceKind.ABS else amount * abs(reference)
    return abs(value - reference) <= allowed + EPSILON
