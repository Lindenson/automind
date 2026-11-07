"""Interpretation: the model proposes a typed case delta; code checks it (R4, FR-003).

The model sees the case file, any pending question or confirmation, the last turns and the criteria keys, and
returns an `Interpretation`. Car references must be existing case keys; an unknown reference raises `InterpretError`
and the person is asked to rephrase instead of a guess. What the model says the person stated (persona, profile,
budget numbers, the engine) is kept only when the person's own words carry it (constitution I).
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from automind.chat.application.services.interpretation.contracts import History, Interpretation, InterpretError
from automind.chat.domain import understanding
from automind.chat.domain.case import CRITERION_KEYS, CarContext, CarRef, CaseDelta, CaseFile, Constraints
from automind.shared.contracts.llm import LLM
from automind.shared.vehicle.engine import EngineHint
from automind.shared.vehicle.identity import parse_engine

HISTORY_WINDOW: tuple[int, int] | None = None  # turns × characters; configure_history() sets it from search.yaml

CRITERIA_HELP = {
    "reliability": "known issues, breakdown statistics",
    "ownership_cost": "maintenance, energy, tyres, tax, repair reserve per year",
    "purchase_price": "official new price (or original price class if used)",
    "practicality": "boot, seats, rear space",
    "comfort": "ride, noise, seats (from reviews)",
    "performance": "acceleration, power-to-weight",
    "driving_fun": "handling, agility, power-to-weight",
    "traction_all_weather": "AWD, winter/rain traction",
    "offroad_mountain": "ground clearance, low range, torque for mountains/off-road",
    "efficiency": "fuel or energy consumption",
    "safety": "Euro NCAP rating",
    "status": "price class + segment + brand positioning (prestige)",
    "engineering": "technical sophistication, powertrain and chassis design",
}


_ENGINE_WORDS = re.compile(
    r"\d+(?:[.,]\d+)?|\b(?:l|tsi|tfsi|tdi|tce|cv|ps|hp|kw|cc|л\.?\s?с\.?|лс|литр\w*|двигател\w*|мотор\w*|"
    r"motor|engine|dm-i|phev|hev|mhev|turbo)\b",
    re.I,
)


async def interpret(llm: LLM, system_prompt: str, case: CaseFile, history: History, user_text: str) -> Interpretation:
    """The model's reading of `user_text`, checked by code: context of a car added in the same message folded into
    it, a car described under an unknown key added as new, persona and profile kept only with the person's words,
    budget/limit/need numbers only when written in this message, the engine read from the words.
    Raises InterpretError when the output does not validate or names a car the case does not have."""
    try:
        out = await llm.structured(
            "interpreter", Interpretation, system_prompt, build_user_prompt(case, history, user_text)
        )
    except (ValidationError, ValueError) as e:
        raise InterpretError(str(e)) from e
    out = _unknown_targets_as_new_cars(case, _fold_new_car_context(case, out))
    _check(case, out.delta)
    said = [user_text, *(m["text"] for m in history if m.get("role") == "user")]
    out = _profile_from_users_words(_persona_from_users_words(out, said), said)
    out = _constraints_from_this_message(out, user_text)
    return engine_hints(out, user_text)


def configure_history(turns: int, chars: int) -> None:
    """Set the window of earlier turns the model sees (search.yaml interpret window; called once at start-up)."""
    global HISTORY_WINDOW
    HISTORY_WINDOW = (max(1, int(turns)), max(100, int(chars)))


def build_user_prompt(case: CaseFile, history: History, user_text: str) -> str:
    """The model's user prompt: the case file (car keys fixed), the pending question, the criteria keys, the last
    turns within the configured window, and the latest message. Raises RuntimeError before `configure_history`."""
    compact = case.model_dump(mode="json", exclude={"shown", "next_car_no"}, exclude_defaults=True)
    criteria = "\n".join(f"- {k}: {CRITERIA_HELP[k]}" for k in CRITERION_KEYS)
    if HISTORY_WINDOW is None:
        raise RuntimeError("configure_history() was not called: search.yaml interpret window unknown")
    turns, chars = HISTORY_WINDOW  # spec 007 FR-005: the profile is inferred from the dialogue, not one message
    hist = "\n".join(f"{m['role']}: {m['text'][:chars]}" for m in history[-turns:]) or "(start of the chat)"
    pending = json.dumps(case.pending.model_dump(mode="json"), ensure_ascii=False) if case.pending else "none"
    return (
        f"CASE FILE (car keys are fixed: {', '.join(c.key for c in case.cars) or 'no cars yet'}):\n"
        f"{json.dumps(compact, ensure_ascii=False)}\n\n"
        f"PENDING (question or confirmation the user may be answering): {pending}\n\n"
        f"CRITERIA KEYS:\n{criteria}\n\n"
        f"LAST TURNS:\n{hist}\n\n"
        f"LATEST USER MESSAGE:\n{user_text}"
    )


def engine_hints(i: Interpretation, user_text: str) -> Interpretation:
    """The engine is identity, not a trim (spec 005 R4, FR-012). Deterministic post-step:
    - an engine written in trim_hint ("1.5", "1.5 TSI 150 CV") moves to engine_hint;
    - the parser fills fields the model left empty; on a conflict the parser's value wins (the user's words); with
      several cars the parser reads each car's own words (its request_text), not the whole message;
    - when exactly one car is touched and the model gave no engine, the engine in the message goes to that car."""
    refs: list[CarRef | CarContext] = [*i.delta.add_cars, *i.delta.replace_cars, *i.delta.set_car_context]
    words = parse_engine(user_text)
    for r in refs:
        k = r.constraints
        if k is None:
            continue
        if k.trim_hint and (e := parse_engine(k.trim_hint)) is not None and (e.displacement_l or e.power_kw):
            k.engine_hint = _merge_engine(k.engine_hint, e)
            if not _ENGINE_WORDS.sub(" ", k.trim_hint).strip(" ,.-"):
                k.trim_hint = None  # nothing but the engine: it was never a trim
        # several cars in one message: each car's own words, never the whole message ("BYD Seal U DM-i or SEAT
        # Ateca 1.5 TSI" gave the Ateca a "DM-i" engine and sent it to the resolver; golden g8)
        own = words if len(refs) == 1 else parse_engine(getattr(r, "request_text", None) or "")
        if k.engine_hint is not None and own is not None:
            k.engine_hint = _merge_engine(k.engine_hint, own)
    touched = [r for r in refs if r.constraints is None or r.constraints.engine_hint is None]
    if words is not None and len(refs) == 1 and touched:
        r = touched[0]
        r.constraints = (r.constraints or Constraints()).model_copy(update={"engine_hint": words})
    return i


def _fold_new_car_context(case: CaseFile, i: Interpretation) -> Interpretation:
    """Context for a car added in the same message ("car#1" while the case has none yet; live run 2026-11-04,
    Gemini) belongs to that new car: its condition, year or hints are folded into the add, not an error."""
    d = i.delta
    keys = {c.key for c in case.cars}
    new = {f"car#{case.next_car_no + n}": ref for n, ref in enumerate(d.add_cars)}
    keep = []
    for ctx in d.set_car_context:
        ref = new.get(ctx.target_key) if ctx.target_key not in keys else None
        if ref is None:
            keep.append(ctx)
            continue
        for f in ("condition", "year", "age_years", "mileage_km"):
            v = getattr(ctx, f, None)
            if v is not None and (getattr(ref, f) in (None, "UNKNOWN")):
                setattr(ref, f, v)
    if len(keep) == len(d.set_car_context):
        return i
    return i.model_copy(update={"delta": d.model_copy(update={"set_car_context": keep})})


def _unknown_targets_as_new_cars(case: CaseFile, i: Interpretation) -> Interpretation:
    """A car described for a key the case does not have is a new car, not an error (009 FR-022, chat 20b5b7f9: the
    first message "a Kia to replace my Prado 150" came back as replace_cars of car#1 in an empty case, and the user
    got "could not map that to the cars we are discussing"). Only a description with a make or a model is kept."""
    d = i.delta
    keys = {c.key for c in case.cars}
    stray = [x for x in (*d.replace_cars, *d.set_car_context) if x.target_key not in keys and (x.make or x.model)]
    if not stray:
        return i
    add = [CarRef(request_text=x.request_text or " ".join(p for p in (x.make, x.model) if p), make=x.make,
                  model=x.model, condition=x.condition or "UNKNOWN", year=x.year, age_years=x.age_years,
                  mileage_km=x.mileage_km, constraints=x.constraints or Constraints()) for x in stray]  # fmt: skip
    gone = {id(x) for x in stray}
    delta = d.model_copy(update={
        "add_cars": [*d.add_cars, *add],
        "replace_cars": [x for x in d.replace_cars if id(x) not in gone],
        "set_car_context": [x for x in d.set_car_context if id(x) not in gone],
    })  # fmt: skip
    return i.model_copy(update={"delta": delta})


def _check(case: CaseFile, delta: CaseDelta) -> None:
    keys = {c.key for c in case.cars}
    refs = [
        *delta.remove_cars,
        *(x.target_key for x in delta.replace_cars),
        *(x.target_key for x in delta.set_car_context),
    ]
    if delta.set_prediction is not None:
        refs.append(delta.set_prediction.winner_key)
    bad = sorted({r for r in refs if r not in keys})
    if bad:
        raise InterpretError(f"unknown car reference(s): {', '.join(bad)}")


def _merge_engine(model: EngineHint | None, parsed: EngineHint) -> EngineHint:
    if model is None:
        return parsed
    data = model.model_dump()
    for f in ("displacement_l", "power_hp", "power_kw", "fuel", "family"):
        p = getattr(parsed, f)
        if p is not None:
            data[f] = p  # the user's words win over the model's reading
    data["evidence"] = data.get("evidence") or parsed.evidence
    return EngineHint.model_validate(data)


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def _said(words: str | None, said: list[str]) -> bool:
    """The words (3+ characters) appear in one of the person's messages, case and spacing ignored."""
    return words is not None and len(words.strip()) >= 3 and any(_norm(words) in _norm(t) for t in said)


def _persona_from_users_words(i: Interpretation, said: list[str]) -> Interpretation:
    """A persona needs the user's own words (spec 007 FR-002; before: this message only). Words from an earlier
    message are an inference: INFERRED, which never overwrites what the user stated or set in the panel."""
    p = i.delta.set_persona
    if p is None:
        return i
    if not _said(i.persona_evidence, said):
        return i.model_copy(update={"delta": i.delta.model_copy(update={"set_persona": None})})
    if _said(i.persona_evidence, said[:1]):
        return i
    basis = {**i.delta.profile_basis, "persona": "INFERRED"}
    delta = i.delta.model_copy(update={"set_persona": p.model_copy(update={"source": "INFERRED"}),
                                       "profile_basis": basis})  # fmt: skip
    return i.model_copy(update={"delta": delta})


def _profile_from_users_words(i: Interpretation, said: list[str]) -> Interpretation:
    """Profile fields (family, age band, driving style) need words the user actually wrote (constitution I);
    words from an earlier message only are INFERRED."""
    p = i.delta.set_profile
    if p is None:
        return i
    keep = {f: w for f, w in p.evidence.items() if _said(w, said)}
    upd = {f: None for f in ("family", "age_band", "driving_style") if getattr(p, f) is not None and f not in keep}
    basis = dict(i.delta.profile_basis)
    for f, w in keep.items():
        if f in ("family", "age_band", "driving_style") and not _said(w, said[:1]):
            basis[f] = "INFERRED"
    return i.model_copy(update={"delta": i.delta.model_copy(update={
        "set_profile": p.model_copy(update={**upd, "evidence": keep}), "profile_basis": basis})})  # fmt: skip


def _constraints_from_this_message(i: Interpretation, user_text: str) -> Interpretation:
    """Numbers in budget, running-cost limit and needs must be written in THIS message (constitution I):
    an amount the model inferred or took from history is dropped; an intent-only budget answer is kept."""
    d = i.delta
    seen = understanding.amounts_in(user_text)

    def ok(v: float | None) -> bool:
        return v is None or any(abs(v - n) <= max(1.0, 0.005 * n) for n in seen)

    upd: dict[str, object] = {}
    if d.set_budget is not None and not ok(d.set_budget.max_eur):
        upd["set_budget"] = (
            d.set_budget.model_copy(update={"max_eur": None}) if d.set_budget.intent != "UNKNOWN" else None
        )
    if d.set_running_cost_limit is not None and not ok(d.set_running_cost_limit.amount_eur):
        upd["set_running_cost_limit"] = None
    if d.set_needs is not None:
        n = d.set_needs
        bad = {k: None for k in ("passengers", "towing_kg", "daily_km") if not ok(getattr(n, k))}
        if bad:
            kept = n.model_copy(update=bad)
            upd["set_needs"] = kept if kept.model_dump(exclude_none=True, exclude_defaults=True) else None
    return i.model_copy(update={"delta": d.model_copy(update=upd)}) if upd else i
