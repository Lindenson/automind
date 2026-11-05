"""Fit the power-mass-acceleration envelope of config/physics.yaml (spec 011 T066, research R8 check 1).

Points: the reference set (`eval/reference_vehicles.yaml`, manufacturer 0-100 times) and catalogue variants whose
shown power and curb mass agree with their gold values and that have a 0-100 time. Prints YAML for a person to review
and paste under `checks.power_mass_accel.envelope`; it never writes the file (constitution XII).

    python -m automind.acquisition.reputation.fit_physics [--min-points 3]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from automind.acquisition.domain.physics import Point, fit_envelope
from automind.acquisition.gold import repo as gold_repo
from automind.infrastructure.db import SpecValue, Variant, sessionmaker

REFERENCE = Path(__file__).resolve().parents[4] / "eval" / "reference_vehicles.yaml"
GOLD_REL = 0.03  # power and mass must agree with gold this closely for a catalogue point


def _group(powertrain: str | None, drivetrain: str | None) -> str:
    return f"{powertrain or 'ICE'}|{drivetrain}" if drivetrain else str(powertrain or "ICE")


def reference_points(path: Path = REFERENCE) -> list[Point]:
    if not path.exists():
        return []
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for v in doc.get("vehicles") or []:
        sp = v.get("specs") or {}
        p, m, t = sp.get("max_power"), sp.get("curb_mass"), sp.get("claimed_0_100")
        if v.get("sources") and p and m and t:
            out.append(Point(_group(v.get("powertrain"), sp.get("drivetrain")), float(m) / float(p), float(t)))
    return out


def _agrees(gold: dict[str, Any], vals: dict[str, Any], attr: str) -> bool:
    g = gold.get(attr)
    return g is not None and g.value_num is not None and abs(g.value_num - float(vals[attr])) <= GOLD_REL * g.value_num


async def catalogue_points() -> list[Point]:
    out = []
    wanted = ("max_power", "curb_mass", "claimed_0_100", "drivetrain")
    async with sessionmaker()() as s:
        rows = (await s.execute(select(SpecValue).where(SpecValue.attribute.in_(wanted)))).scalars()
        by: dict[str, dict[str, Any]] = {}
        for r in rows:
            by.setdefault(r.variant_id, {})[r.attribute] = r.value_num if r.value_num is not None else r.value_text
        for vid, vals in by.items():
            p, m, t = vals.get("max_power"), vals.get("curb_mass"), vals.get("claimed_0_100")
            if not (p and m and t):
                continue
            gold = gold_repo.best_by_attribute(await gold_repo.gold_for(vid))
            if not (_agrees(gold, vals, "max_power") and _agrees(gold, vals, "curb_mass")):
                continue
            v = await s.get(Variant, vid)
            group = _group(v.powertrain if v else None, str(vals.get("drivetrain") or "") or None)
            out.append(Point(group, float(m) / float(p), float(t)))
    return out


async def main_async(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="fit_physics", description="Fit the power-mass-acceleration envelope")
    ap.add_argument("--min-points", type=int, default=3)
    args = ap.parse_args(argv)
    points = reference_points() + await catalogue_points()
    env = fit_envelope(points, args.min_points)
    print(f"# {len(points)} points; review before pasting under checks.power_mass_accel.envelope")
    print(yaml.safe_dump({"envelope": env}, sort_keys=True, default_flow_style=None))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(sys.argv[1:])))
