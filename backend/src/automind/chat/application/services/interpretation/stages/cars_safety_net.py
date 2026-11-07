"""The safety net under the interpreter for named cars: two named cars are a comparison even when the model called the
message a general question or returned a comparison without cars (live run 2026-11-04, twice)."""

from __future__ import annotations

from automind.chat.domain import understanding
from automind.chat.domain.case import CarRef, CaseDelta, CaseFile, Constraints, apply
from automind.chat.domain.decision import RequestKind
from automind.shared.contracts.config import MakeNames
from automind.shared.vehicle.identity import parse_engine

MAX_FOUND = 3  # at most three cars are compared


def cars_safety_net(new: CaseFile, text: str, makes: MakeNames | None, year: int,
                    request: RequestKind) -> tuple[CaseFile, RequestKind, list[str]]:  # fmt: skip
    """(case, request, change log): with two or more makes in the words, their cars are added and the request is a
    comparison; otherwise everything is returned unchanged."""
    found = understanding.cars_in_text(text, makes.match_make) if makes is not None else []
    if len(found) < 2:
        return new, request, []
    cond = understanding.condition_of(text) or "UNKNOWN"
    refs = [CarRef(request_text=words, make=make, condition=cond,
                   constraints=Constraints(engine_hint=parse_engine(words)))
            for words, make in found[:MAX_FOUND]]  # fmt: skip
    out, log = apply(new, CaseDelta(add_cars=refs), current_year=year)
    return out, "compare", ["cars from the user's words (the interpreter found none)", *log]
