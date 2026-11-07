"""Block tco: the ownership cost per car and item, with the sources of each item."""

from __future__ import annotations

from dataclasses import asdict

from automind.acquisition import api as acquisition
from automind.chat.domain.cost import tco
from automind.shared.contracts.json import JsonObject


def tco_block(estimates: list[tco.TcoEstimate], evidence: dict[str, JsonObject] | None = None) -> JsonObject:
    ev = evidence or {}
    years = estimates[0].years if estimates else 5
    return {
        "type": "tco",
        "title": f"Ownership cost (over {years} years including depreciation; running costs per year)",
        "annual_km": estimates[0].annual_km if estimates else 15000,
        "years": years,
        "cars": [
            {
                "car_id": e.car_id,
                "label": e.label,
                "condition": "USED" if e.condition == "USED" else "NEW",
                "age_years": e.age_years,
                "annual_total": e.annual_total,
                "five_year_total": e.five_year_total,
                **({"depreciation_left_out": True} if e.depreciation_left_out else {}),
                "items": [
                    {
                        "kind": i.kind,
                        "label": i.label,
                        "annual_eur": i.annual_eur,
                        "five_year_eur": i.five_year_eur,
                        "basis": i.basis,
                        "inputs": i.inputs,
                        "sources": [ev[x] for x in i.evidence_ids if x in ev],
                        **({"parts": [asdict(x) for x in i.parts]} if i.parts else {}),
                        **({"missing": i.missing} if i.missing else {}),
                    }
                    for i in e.items
                ],
            }
            for e in estimates
        ],
    }


async def evidence_refs(ids: list[str]) -> dict[str, JsonObject]:
    return await acquisition.evidence_refs(ids)
