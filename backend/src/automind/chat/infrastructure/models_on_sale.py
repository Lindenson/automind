"""Models on sale in Spain known without a new search (spec 007 US7): the cached line-ups and the catalog."""

from __future__ import annotations

from sqlalchemy import select

from automind.chat.domain import intake
from automind.shared.infrastructure import db

_PT = {"ICE": "petrol", "HEV": "hybrid", "MHEV": "mhev", "PHEV": "phev", "BEV": "bev"}


async def models_on_sale() -> list[tuple[str, intake.LineupModel]]:
    """(make, model) known to be sold in Spain: line-ups first; catalogued models fill in body and the lowest price."""
    found: dict[tuple[str, str], intake.LineupModel] = {}
    async with db.sessionmaker()() as s:
        for row in (await s.execute(select(db.BrandLineup).where(db.BrandLineup.market == "ES"))).scalars():
            for m in row.models or []:
                name = str(m.get("model") or "").strip()
                if name:
                    found[(row.make, name.lower())] = intake.LineupModel(
                        model=name, body=str(m.get("body") or "").lower(),
                        powertrains=tuple(m.get("powertrains") or ()), price_from_eur=m.get("price_from_eur"),
                        source_url=m.get("source_url"),
                    )  # fmt: skip
        for v in (await s.execute(select(db.Variant).where(db.Variant.market == "ES"))).scalars():
            key = (v.make, v.model.lower())
            have = found.get(key)
            price = int(v.price_eur) if v.price_eur else None
            pts = tuple({*(have.powertrains if have else ()), _PT.get(v.powertrain, "petrol")})
            body = have.body if have and have.body else (v.body_class or "").lower()
            prices = [x for x in (price, have.price_from_eur if have else None) if x]
            low = min(prices) if prices else None
            found[key] = intake.LineupModel(
                model=have.model if have else v.model, body=body, powertrains=pts, price_from_eur=low,
                source_url=have.source_url if have else None,
            )  # fmt: skip
    return [(mk, m) for (mk, _), m in sorted(found.items())]
