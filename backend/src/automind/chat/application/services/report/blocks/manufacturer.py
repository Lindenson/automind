"""Block manufacturer: the makes' facts (warranty, network, market share, finances), two per kind."""

from __future__ import annotations

from automind.chat.application.services.report.contracts import LoadedCar
from automind.chat.application.services.report.facts.car import manufacturer_facts
from automind.shared.contracts.json import JsonObject


def manufacturer_block(cars: list[LoadedCar]) -> JsonObject | None:
    makes: dict[str, list[JsonObject]] = {}
    for c in cars:
        make = c["variant"].make
        if make in makes:
            continue
        makes[make] = [
            {
                "kind": f.fact_type,
                "text": f.text,
                "year": getattr(f, "year", None),
                "sources": [
                    {
                        "name": f.source_name or f.url,
                        "url": f.url,
                        "type": "PUBLICATION",
                        "retrieved_at": f.retrieved_at.isoformat(),
                        "excerpt": f.excerpt,
                    }
                ],
            }
            for f in manufacturer_facts(c.get("manufacturer_facts", []))
        ]
    if not makes:
        return None
    # spec 004 FR-006: fewer than two facts for a make is shown as insufficient, with "find it"
    return {
        "type": "manufacturer",
        "title": "Manufacturer",
        "makes": [{"make": m, "facts": f, "insufficient": len(f) < 2} for m, f in makes.items()],
    }
