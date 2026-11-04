"""Interpretation: the LLM proposes a typed case delta; code validates it (R4, FR-003).

The model sees the case file, any pending question or confirmation, the last turns and the
criteria keys. It returns `Interpretation`. Car references must be existing case keys; unknown
references raise `InterpretError`, and the hub asks the user to rephrase instead of guessing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from automind.application.ports import LLM
from automind.domain.casefile import CRITERION_KEYS, CaseDelta, CaseFile, Constraints, EngineHint
from automind.domain.identity import parse_engine
from automind.domain.policy import RequestKind


class Interpretation(BaseModel):
    request: RequestKind = Field(
        description="compare: compare/recommend cars; single: one car; follow_up_question: question about cars "
        "already discussed; weights_change: priorities/what matters changed; correction: user corrects a car or "
        "a fact; research_more: the user asks to find missing data, search again or redo/update the report "
        "('why is there no data for X? find it', 'update the report', 'look deeper'); general_question: general "
        "automotive knowledge; confirm_yes/confirm_no: answer to a pending confirmation; choose_for_me: the user "
        "lets the hub pick the version ('any', 'choose for me', 'любой', 'на твой выбор', 'cualquiera'); "
        "critique: the user is unhappy with the report ('bad', 'useless', 'incomplete', 'плохо', 'фигня', 'malo'), "
        "with focus_cars / focus_areas when they name what is wrong; "
        "chitchat: greetings/other"
    )
    language: str = Field(description="ISO 639-1 code of the user's message, e.g. 'ru', 'en', 'es'")
    delta: CaseDelta = Field(default_factory=CaseDelta, description="Changes to the case file stated in THIS message")
    persona_evidence: str | None = Field(
        default=None,
        description="Verbatim words the user wrote (this or an earlier message) that show who they are; required "
        "to set_persona",
    )
    focus_cars: list[str] = Field(
        default_factory=list, description="research_more: car keys the user named (empty = all cars)"
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="research_more: research areas the user named (specs, price, maintenance, reliability, "
        "reviews, measured, engineering, manufacturer, depreciation); empty = every area below its minimum",
    )
    constraints_evidence: list[str] = Field(
        default_factory=list,
        description="Verbatim words from the LATEST message that contain the numbers set in set_budget, "
        "set_running_cost_limit or set_needs",
    )


HISTORY_WINDOW = (16, 800)  # turns × characters; configure_history() sets it from search.yaml


def configure_history(turns: int, chars: int) -> None:
    global HISTORY_WINDOW
    HISTORY_WINDOW = (max(1, int(turns)), max(100, int(chars)))


class InterpretError(ValueError):
    """The model output could not be validated against the case (→ ASK the user to rephrase)."""


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


def build_user_prompt(case: CaseFile, history: list[dict[str, str]], user_text: str) -> str:
    compact = case.model_dump(mode="json", exclude={"shown", "next_car_no"}, exclude_defaults=True)
    criteria = "\n".join(f"- {k}: {CRITERIA_HELP[k]}" for k in CRITERION_KEYS)
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


async def interpret(
    llm: LLM, system_prompt: str, case: CaseFile, history: list[dict[str, str]], user_text: str
) -> Interpretation:
    try:
        out = await llm.structured(
            "interpreter", Interpretation, system_prompt, build_user_prompt(case, history, user_text)
        )
    except (ValidationError, ValueError) as e:
        raise InterpretError(str(e)) from e
    _check(case, out.delta)
    said = [user_text, *(m["text"] for m in history if m.get("role") == "user")]
    out = _profile_from_users_words(_persona_from_users_words(out, said), said)
    out = _constraints_from_this_message(out, user_text)
    return engine_hints(out, user_text)


def engine_hints(i: Interpretation, user_text: str) -> Interpretation:
    """The engine is identity, not a trim (spec 005 R4, FR-012). Deterministic post-step:
    - an engine written in trim_hint ("1.5", "1.5 TSI 150 CV") moves to engine_hint;
    - the parser fills fields the model left empty; on a conflict the parser's value wins (the user's words); with
      several cars the parser reads each car's own words (its request_text), not the whole message;
    - when exactly one car is touched and the model gave no engine, the engine in the message goes to that car."""
    refs = [*i.delta.add_cars, *(x for x in i.delta.replace_cars), *(x for x in i.delta.set_car_context)]
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


_ENGINE_WORDS = re.compile(
    r"\d+(?:[.,]\d+)?|\b(?:l|tsi|tfsi|tdi|tce|cv|ps|hp|kw|cc|л\.?\s?с\.?|лс|литр\w*|двигател\w*|мотор\w*|"
    r"motor|engine|dm-i|phev|hev|mhev|turbo)\b",
    re.I,
)


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
    return bool(words) and len(words.strip()) >= 3 and any(_norm(words) in _norm(t) for t in said)


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


# "20к" / "20k" is 20,000 but "20 км" / "20 km" is a distance (reviewer 2026-11-03: the Cyrillic к was missed).
# A space joins digits only as a thousands group ("25 000"); "Golf 7 2015" is 7 and 2015 (spec 007 FR-004).
_NUM_RE = re.compile(
    r"(\d{1,3}(?:[\s\u00a0.,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?)\s*"
    r"([kк](?![a-zа-яё])|mil\b|тыс\w*|тыщ\w*|thousand|млн\w*|mill[oó]n\w*|million\w*)?",
    re.I,
)


def _multiplier(word: str | None) -> float:
    if not word:
        return 1.0
    w = word.lower()
    return 1_000_000.0 if w.startswith(("млн", "mill")) else 1000.0


def numbers_in(text: str) -> set[float]:
    """Numbers written in a message: '25.000', '25,000', '25 000', '25k', '25 mil', '25 тыс', 'до 20 тыщ' → 25000,
    20000; '1,5 млн' → 1,500,000."""
    out: set[float] = set()
    for m in _NUM_RE.finditer(text):
        raw = re.sub(r"\s", "", m.group(1))
        if re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw) and not (m.group(2) and re.fullmatch(r"\d[.,]\d{3}", raw)
                                                           and _multiplier(m.group(2)) > 1000):  # fmt: skip
            raw = raw.replace(".", "").replace(",", "")
        else:
            raw = raw.replace(",", ".")
        try:
            v = float(raw)
        except ValueError:
            continue
        out.add(round(v * _multiplier(m.group(2)), 6))
    return out


def _constraints_from_this_message(i: Interpretation, user_text: str) -> Interpretation:
    """Numbers in budget, running-cost limit and needs must be written in THIS message (constitution I):
    an amount the model inferred or took from history is dropped; an intent-only budget answer is kept."""
    d = i.delta
    seen = numbers_in(user_text)

    def ok(v: float | None) -> bool:
        return v is None or any(abs(v - n) <= max(1.0, 0.005 * n) for n in seen)

    upd: dict[str, Any] = {}
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


def summarize(i: Interpretation) -> dict[str, Any]:
    """Compact form stored in graph state."""
    return i.model_dump(mode="json", exclude_defaults=True)
