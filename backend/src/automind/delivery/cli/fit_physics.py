"""`python -m automind.cli fit-physics [--min-points 3]`: fit the power-mass-acceleration envelope of
config/physics.yaml (spec 011 T066) from the reference set and the gold-checked catalogue. Prints YAML for a person
to review and paste under `checks.power_mass_accel.envelope`; it never writes the file (constitution XII)."""

from __future__ import annotations

import argparse

import yaml

from automind.acquisition.domain.physics import fit_envelope
from automind.acquisition.reputation.infrastructure.physics_points import catalogue_points, reference_points


async def main_async(argv: list[str]) -> int:
    """Print the fitted envelope; 0."""
    ap = argparse.ArgumentParser(prog="fit_physics", description="Fit the power-mass-acceleration envelope")
    ap.add_argument("--min-points", type=int, default=3)
    args = ap.parse_args(argv)
    points = reference_points() + await catalogue_points()
    env = fit_envelope(points, args.min_points)
    print(f"# {len(points)} points; review before pasting under checks.power_mass_accel.envelope")
    print(yaml.safe_dump({"envelope": env}))  # to stdout only: a person pastes it
    return 0
