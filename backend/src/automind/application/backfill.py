"""Fill engine_cc / power_kw / fuel of stored variants from their names (spec 005 T007, research R4).

Deterministic: `identity.parse_engine` on `variant_name`; powertrain BEV/PHEV/HEV/MHEV maps to the fuel when the
name says nothing. Rows already filled are kept; unparsed rows stay null.
"""

from __future__ import annotations

from sqlalchemy import select

from automind.domain.identity import parse_engine
from automind.infrastructure import db

_PT_FUEL = {"BEV": "bev", "PHEV": "phev", "HEV": "hybrid", "MHEV": "mhev"}


async def backfill_engines() -> dict[str, int]:
    counts = {"variants": 0, "filled": 0, "unparsed": 0}
    async with db.sessionmaker()() as s:
        for v in (await s.execute(select(db.Variant))).scalars():
            counts["variants"] += 1
            if v.engine_cc or v.power_kw or v.fuel:
                continue
            e = parse_engine(v.variant_name)
            fuel = (e.fuel if e else None) or _PT_FUEL.get(v.powertrain)
            if e is None and fuel is None:
                counts["unparsed"] += 1
                continue
            if e is not None:
                v.engine_cc = round(e.displacement_l * 1000) if e.displacement_l else None
                v.power_kw = e.power_kw
            v.fuel = fuel
            counts["filled"] += 1
        await s.commit()
    return counts
