"""The engine read from the person's words (spec 005 R4, FR-012; moved from `interpretation.interpret`, spec 013
T032): an engine is identity, not a trim, and the person's words win over the model's reading. Used by the old
interpreter and by `validate_understanding`. Pure apart from reshaping the delta's car references in place."""

from __future__ import annotations

import re

from automind.chat.domain.case import CarContext, CarRef, CaseDelta, Constraints
from automind.shared.vehicle.engine import EngineHint
from automind.shared.vehicle.identity import parse_engine

_ENGINE_WORDS = re.compile(
    r"\d+(?:[.,]\d+)?|\b(?:l|tsi|tfsi|tdi|tce|cv|ps|hp|kw|cc|л\.?\s?с\.?|лс|литр\w*|двигател\w*|мотор\w*|"
    r"motor|engine|dm-i|phev|hev|mhev|turbo)\b",
    re.I,
)


def engine_hints(d: CaseDelta, text: str) -> CaseDelta:
    """The engine is identity, not a trim (spec 005 R4, FR-012), read from the words (the delta's refs, in place):
    - an engine written in trim_hint ("1.5", "1.5 TSI 150 CV") moves to engine_hint;
    - the parser fills fields the model left empty; on a conflict the parser's value wins (the person's words); with
      several cars the parser reads each car's own words (its request_text), not the whole message;
    - when exactly one car is touched and the model gave no engine, the engine in the message goes to that car."""
    refs: list[CarRef | CarContext] = [*d.add_cars, *d.replace_cars, *d.set_car_context]
    words = parse_engine(text)
    for r in refs:
        k = r.constraints
        if k is None:
            continue
        if k.trim_hint and (e := parse_engine(k.trim_hint)) is not None and (e.displacement_l or e.power_kw):
            k.engine_hint = _merge_engine(k.engine_hint, e)
            if not _ENGINE_WORDS.sub(" ", k.trim_hint).strip(" ,.-"):
                k.trim_hint = None  # nothing but the engine: it was never a trim
        # several cars in one message: each car's own words, never the whole message (golden g8)
        own = words if len(refs) == 1 else parse_engine(r.request_text or "")
        if k.engine_hint is not None and own is not None:
            k.engine_hint = _merge_engine(k.engine_hint, own)
    touched = [r for r in refs if r.constraints is None or r.constraints.engine_hint is None]
    if words is not None and len(refs) == 1 and touched:
        r = touched[0]
        r.constraints = (r.constraints or Constraints()).model_copy(update={"engine_hint": words})
    return d


def _merge_engine(model: EngineHint | None, parsed: EngineHint) -> EngineHint:
    if model is None:
        return parsed
    data = model.model_dump()
    for f in ("displacement_l", "power_hp", "power_kw", "fuel", "family"):
        p = getattr(parsed, f)
        if p is not None:
            data[f] = p  # the person's words win over the model's reading
    data["evidence"] = data.get("evidence") or parsed.evidence
    return EngineHint.model_validate(data)
