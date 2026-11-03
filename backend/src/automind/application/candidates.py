"""Candidates when no car is named (spec 007 US7): "посоветуй семейный кроссовер до 25к".

The pool is what is known without a new search (the port `models_on_sale`: cached Spanish line-ups and the
catalog); `domain.intake.pick_candidates` ranks it for the person; the cars then go through the usual
identification, the confirmation card and research.
"""

from __future__ import annotations

from automind.application.identify import fit_of
from automind.application.ports import Ports
from automind.domain import intake
from automind.domain.casefile import CaseCar, CaseFile


async def propose(ports: Ports, case: CaseFile, limit: int = 3) -> list[dict[str, object]]:
    """Add 2–3 candidate cars to the case (in place); returns what was proposed, [] when nothing fits."""
    if ports.models_on_sale is None:
        return []
    picked = intake.pick_candidates(await ports.models_on_sale(), fit_of(case), case.wanted_body, limit=limit)
    if len(picked) < 2:
        return []
    condition = "USED" if case.budget.intent == "USED" else "NEW"
    out: list[dict[str, object]] = []
    for make, m, why in picked:
        key = f"car#{case.next_car_no}"
        case.next_car_no += 1
        case.cars.append(CaseCar(key=key, request_text=f"{make} {m.model}", make=make, model=m.model,
                                 condition=condition))  # type: ignore[arg-type]  # fmt: skip
        out.append({"key": key, "make": make, "model": m.model, "why": why, "price_from_eur": m.price_from_eur})
    case.candidates = out
    return out
