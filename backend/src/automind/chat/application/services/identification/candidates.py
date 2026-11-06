"""Candidates when no car is named (spec 007 US7): "посоветуй семейный кроссовер до 25к"; or a make is named
without a model (009 FR-022): "найди мне подходящую kia для замены моего прадо 150".

The pool is what is known without a new search (the port `models_on_sale`: cached Spanish line-ups and the
catalog); `domain.intake.pick_candidates` ranks it for the person; the cars then go through the usual
identification, the confirmation card and research. With a make to choose from, only that make's models are
proposed, of the body of the car they replace when it is known.
"""

from __future__ import annotations

from automind.chat.application.ports import Ports
from automind.chat.domain import intake
from automind.chat.domain.case import CaseCar, CaseFile, Fit


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def _replaced_body(pool: list[tuple[str, intake.LineupModel]], case: CaseFile) -> str | None:
    """The body class of the car the purchase replaces, from what is known of it (line-ups, catalog)."""
    for car in case.cars:
        if not car.replaced:
            continue
        for mk, m in pool:
            if _same(mk, car.make) and _same(m.model, car.model) and (body := intake.body_class_of(m.body)):
                return body
    return None


def ask_the_model(case: CaseFile) -> str | None:
    """No candidates of the make to choose from are known: the make becomes a car, so identification asks "which
    model?" with the make's line-up (never an endless general answer). Returns the change, or None."""
    make = case.wanted_make
    if not make or any(_same(c.make, make) and not c.replaced for c in case.cars):
        return None
    key = f"car#{case.next_car_no}"
    case.next_car_no += 1
    case.cars.append(CaseCar(key=key, request_text=make, make=make, condition="NEW" if case.budget.intent != "USED"
                             else "USED"))  # fmt: skip
    return f"{key} added: {make} (no candidates known, the model is asked)"


async def propose(ports: Ports, case: CaseFile, limit: int = 3) -> list[dict[str, object]]:
    """Add 2–3 candidate cars to the case (in place); returns what was proposed, [] when nothing fits."""
    if ports.models_on_sale is None:
        return []
    known = await ports.models_on_sale()
    pool = known
    reg = ports.ref.makes
    if reg is not None:  # only makes of the registry: never a renamed or unknown catalog row
        pool = [(mk, m) for mk, m in pool if reg.canonical(mk) is not None]
    body = case.wanted_body
    if case.wanted_make:
        make = reg.canonical(case.wanted_make) if reg is not None else None
        pool = [(mk, m) for mk, m in pool if _same(mk, make or case.wanted_make)]
        body = body or _replaced_body(known, case)
    fit = Fit.from_case(case)
    picked = intake.pick_candidates(pool, fit, body, limit=limit)
    if len(picked) < 2 and case.wanted_make and body and not case.wanted_body:
        picked = intake.pick_candidates(pool, fit, None, limit=limit)  # the make has no model of that body
    if len(picked) < 2:
        return []
    condition = "USED" if case.budget.intent == "USED" else "NEW"
    out: list[dict[str, object]] = []
    for make, m, why in picked:
        key = f"car#{case.next_car_no}"
        case.next_car_no += 1
        # the hub chose the model, so it takes the base version too: the card shows it and the user may change it,
        # but a proposal never starts with "which engine?" (009 FR-022)
        case.cars.append(CaseCar(key=key, request_text=f"{make} {m.model}", make=make, model=m.model,
                                 condition=condition, chosen_for_me=True))  # type: ignore[arg-type]  # fmt: skip
        out.append({"key": key, "make": make, "model": m.model, "why": why, "price_from_eur": m.price_from_eur})
    case.candidates = out
    return out
