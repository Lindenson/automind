"""Interpretation: the LLM proposes a typed case delta; code validates it (R4, FR-003).

The model sees the case file, any pending question or confirmation, the last turns and the
criteria keys. It returns `Interpretation`. Car references must be existing case keys; unknown
references raise `InterpretError`, and the hub asks the user to rephrase instead of guessing.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from automind.application.ports import LLM
from automind.domain.casefile import CRITERION_KEYS, CaseDelta, CaseFile
from automind.domain.policy import RequestKind


class Interpretation(BaseModel):
    request: RequestKind = Field(
        description="compare: compare/recommend cars; single: one car; follow_up_question: question about cars "
        "already discussed; weights_change: priorities/what matters changed; correction: user corrects a car or "
        "a fact; general_question: general automotive knowledge; confirm_yes/confirm_no: answer to a pending "
        "confirmation; chitchat: greetings/other"
    )
    language: str = Field(description="ISO 639-1 code of the user's message, e.g. 'ru', 'en', 'es'")
    delta: CaseDelta = Field(default_factory=CaseDelta, description="Changes to the case file stated in THIS message")
    persona_evidence: str | None = Field(
        default=None,
        description="Verbatim words from the LATEST user message that show who the user is (required to set_persona)",
    )


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
    hist = "\n".join(f"{m['role']}: {m['text'][:500]}" for m in history[-12:]) or "(start of the chat)"
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
    return _persona_from_this_message(out, user_text)


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def _persona_from_this_message(i: Interpretation, user_text: str) -> Interpretation:
    """A persona may change only on words of THIS message (never re-derived from history), so a
    persona the user set in the case panel is not silently overwritten (FR-005a, FR-009)."""
    ev = i.persona_evidence
    if i.delta.set_persona is None or (ev and len(ev.strip()) >= 3 and _norm(ev) in _norm(user_text)):
        return i
    return i.model_copy(update={"delta": i.delta.model_copy(update={"set_persona": None})})


def summarize(i: Interpretation) -> dict[str, Any]:
    """Compact form stored in graph state."""
    return i.model_dump(mode="json", exclude_defaults=True)
