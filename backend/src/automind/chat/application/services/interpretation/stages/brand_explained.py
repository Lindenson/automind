"""A brand the person explains while a question is pending ("BYD is Build Your Dream, Chinese") sets the make of the
car the question is about."""

from __future__ import annotations

from automind.chat.domain.case import CaseFile
from automind.shared.contracts.config import MakeNames


def brand_from_text(new: CaseFile, before: CaseFile, text: str, makes: MakeNames | None) -> list[str]:
    """Sets the make (in place) of each pending car without one when the words name a make. Returns the change log."""
    make = makes.match_make(text) if makes is not None else None
    if not make or before.pending is None:
        return []
    keys = [str(it.get("car")) for it in before.pending.items if it.get("car")]
    out = []
    for car in new.cars:
        if car.key in keys and not car.make:
            car.make = make
            out.append(f"{car.key}: make {make}")
    return out
