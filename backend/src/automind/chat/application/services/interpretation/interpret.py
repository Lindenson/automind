"""Interpretation: the model proposes a typed case delta; code checks it (R4, FR-003).

The model sees the case file, any pending question or confirmation, the last turns and the criteria keys, and
returns an `Interpretation`. Car references must be existing case keys; an unknown reference raises `InterpretError`
and the person is asked to rephrase instead of a guess. What the model says the person stated (persona, profile,
budget numbers, the engine) is kept only when the person's own words carry it (constitution I).
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from automind.chat.application.services.interpretation.contracts import History, Interpretation, InterpretError
from automind.chat.application.services.understanding import checks, engine
from automind.chat.application.services.understanding.understander import CRITERIA_HELP
from automind.chat.domain.case import CRITERION_KEYS, CaseDelta, CaseFile
from automind.shared.contracts.llm import LLM

HISTORY_WINDOW: tuple[int, int] | None = None  # turns × characters; configure_history() sets it from search.yaml


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
    """The engine read from the words (`understanding.engine.engine_hints`, in place)."""
    engine.engine_hints(i.delta, user_text)
    return i


def _on_delta(i: Interpretation, d: CaseDelta) -> Interpretation:
    return i if d is i.delta else i.model_copy(update={"delta": d})


def _fold_new_car_context(case: CaseFile, i: Interpretation) -> Interpretation:
    return _on_delta(i, checks.fold_new_car_context(case, i.delta))


def _unknown_targets_as_new_cars(case: CaseFile, i: Interpretation) -> Interpretation:
    return _on_delta(i, checks.unknown_targets_as_new_cars(case, i.delta))


def _check(case: CaseFile, delta: CaseDelta) -> None:
    bad = checks.unknown_refs(case, delta)
    if bad:
        raise InterpretError(f"unknown car reference(s): {', '.join(bad)}")


def _persona_from_users_words(i: Interpretation, said: list[str]) -> Interpretation:
    return _on_delta(i, checks.persona_from_words(i.delta, i.persona_evidence, said)[0])


def _profile_from_users_words(i: Interpretation, said: list[str]) -> Interpretation:
    return _on_delta(i, checks.profile_from_words(i.delta, said)[0])


def _constraints_from_this_message(i: Interpretation, user_text: str) -> Interpretation:
    return _on_delta(i, checks.constraints_from_message(i.delta, user_text)[0])
