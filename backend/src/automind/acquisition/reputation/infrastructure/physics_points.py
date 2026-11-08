"""The points the power-mass-acceleration envelope is fitted to (spec 011 T066, research R8 check 1): the reference
set (`eval/reference_vehicles.yaml`, manufacturer 0-100 times) and catalogue versions whose shown power and curb mass
agree with their gold values and that have a 0-100 time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from automind.acquisition.domain.physics import Point
from automind.acquisition.gold.domain.records import StoredGold
from automind.acquisition.gold.infrastructure.wiring import gold_store
from automind.shared.infrastructure.db.models import SpecValue, Variant
from automind.shared.infrastructure.db.session import sessionmaker

REFERENCE = Path(__file__).resolve().parents[5] / "eval" / "reference_vehicles.yaml"
GOLD_REL = 0.03  # power and mass must agree with gold this closely for a catalogue point
_WANTED = ("max_power", "curb_mass", "claimed_0_100", "drivetrain")


def reference_points(path: Path = REFERENCE) -> list[Point]:
    """The reference vehicles with a source, power, mass and a 0-100 time."""
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


async def catalogue_points() -> list[Point]:
    """Catalogue versions whose power and mass agree with gold and that have a 0-100 time."""
    out = []
    async with sessionmaker()() as s:
        rows = (await s.execute(select(SpecValue).where(SpecValue.attribute.in_(_WANTED)))).scalars()
        by: dict[str, dict[str, Any]] = {}
        for r in rows:
            by.setdefault(r.variant_id, {})[r.attribute] = r.value_num if r.value_num is not None else r.value_text
        for vid, vals in by.items():
            p, m, t = vals.get("max_power"), vals.get("curb_mass"), vals.get("claimed_0_100")
            if not (p and m and t):
                continue
            gold = await gold_store().best(vid)
            if not (_agrees(gold, vals, "max_power") and _agrees(gold, vals, "curb_mass")):
                continue
            v = await s.get(Variant, vid)
            group = _group(v.powertrain if v else None, str(vals.get("drivetrain") or "") or None)
            out.append(Point(group, float(m) / float(p), float(t)))
    return out


def _group(powertrain: str | None, drivetrain: str | None) -> str:
    return f"{powertrain or 'ICE'}|{drivetrain}" if drivetrain else str(powertrain or "ICE")


def _agrees(gold: dict[str, StoredGold], vals: dict[str, Any], attr: str) -> bool:
    g = gold.get(attr)
    return g is not None and g.value_num is not None and abs(g.value_num - float(vals[attr])) <= GOLD_REL * g.value_num
