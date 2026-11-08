"""The values a car's research must find: the critical specs and the energy inputs of its powertrain."""

from __future__ import annotations

from automind.shared.research_order import plan as research_plan

CRITICAL = ("max_power", "max_torque", "curb_mass", "drivetrain", "claimed_0_100", "top_speed")


def missing_critical(have: set[str], powertrain: str | None = None) -> list[str]:
    """The critical attributes not in `have`, then the energy inputs the powertrain still lacks."""
    return [k for k in CRITICAL if k not in have] + research_plan.energy_inputs_missing(powertrain, have)
