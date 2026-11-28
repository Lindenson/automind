"""The Understander (spec 013 T032, understanding-spec §5.1): one structured model call that reads a typed message
into an `Understanding`. It does not look at keywords and does not change the case.

The model sees the case file (car keys fixed), the open question with its id and option ids, a summary of the bot's
last answer (for `reaction`), the last turns and the message (understanding-spec §6). The role is `understander`
(config/models.yaml: the cheap fast model, decision G4).

Errors: an output that cannot be read raises `UnderstandError` (the reading is refused, nothing is guessed); a
provider failure or a spent budget propagates as the gateway raises it."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from pydantic import ValidationError

from automind.chat.domain.case import CRITERION_KEYS, CaseFile
from automind.chat.domain.turn import Role
from automind.chat.domain.understanding.intent import Understanding
from automind.chat.domain.understanding.open_question import OpenQuestion
from automind.shared.contracts.llm import LLM
from automind.shared.provenance.served import served

ROLE = "understander"
LAST_ANSWER_CHARS = 600  # the bot's last answer as the model sees it (for `reaction`)
History = list[dict[str, str]]  # the last turns, oldest first: {"role": "user" | "assistant", "text": …}

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


class UnderstandError(ValueError):
    """The model's output could not be read as an `Understanding` (the reading is refused)."""


@dataclass(frozen=True)
class ModelReading:
    """What the model returned, which model and prompt answered, and how long the call took."""

    understanding: Understanding
    model: str | None
    prompt_version: str | None
    latency_ms: int


@dataclass(frozen=True)
class Message:
    """One typed message in its context: the case, the open question, the last turns and the words."""

    case: CaseFile
    question: OpenQuestion | None
    history: History
    text: str
    note: str | None = None  # what code found missing in a first reading (spec 013 S4: makes named, no car read)


class Understander:
    """Reads one typed message with the model (`ROLE`), over the system prompt `understander.md`."""

    def __init__(self, llm: LLM, system_prompt: str, window: tuple[int, int]) -> None:
        """`window`: how many earlier turns the model sees and how many characters of each."""
        self.llm, self.system_prompt, self.window = llm, system_prompt, window

    async def read(self, m: Message) -> ModelReading:
        """The model's reading of `m.text`. Raises `UnderstandError` for an output that does not validate."""
        started = time.monotonic()
        try:
            u = await self.llm.structured(ROLE, Understanding, self.system_prompt, self.user_prompt(m))
        except (ValidationError, ValueError) as e:
            raise UnderstandError(str(e)[:500]) from e
        latency = int((time.monotonic() - started) * 1000)
        call = served(ROLE)
        return ModelReading(u, call.model if call else None, call.prompt_key if call else None, latency)

    def user_prompt(self, m: Message) -> str:
        """CASE FILE, PENDING, LAST ANSWER, HISTORY, MESSAGE (understanding-spec §6) and the criteria keys."""
        compact = m.case.model_dump(mode="json", exclude={"shown", "next_car_no", "pending", "intake"},
                                    exclude_defaults=True)  # fmt: skip
        turns, chars = self.window
        hist = "\n".join(f"{x['role']}: {x['text'][:chars]}" for x in m.history[-turns:]) or "(start of the chat)"
        pending = json.dumps(m.question.model_dump(mode="json"), ensure_ascii=False) if m.question else "null"
        criteria = "\n".join(f"- {k}: {CRITERIA_HELP[k]}" for k in CRITERION_KEYS)
        return (
            f"CASE FILE (car keys are fixed: {', '.join(c.key for c in m.case.cars) or 'no cars yet'}):\n"
            f"{json.dumps(compact, ensure_ascii=False)}\n\n"
            f"PENDING: {pending}\n\n"
            f"LAST ANSWER: {_last_answer(m.history)}\n\n"
            f"HISTORY:\n{hist}\n\n"
            f"CRITERIA KEYS:\n{criteria}\n\n"
            f"MESSAGE:\n{m.text}" + (f"\n\nCHECK OF YOUR FIRST READING: {m.note}" if m.note else "")
        )


def _last_answer(history: History) -> str:
    said = next((x["text"] for x in reversed(history) if x.get("role") == Role.ASSISTANT), None)
    if not said:
        return "(none)"
    flat = " ".join(said.split())
    return flat if len(flat) <= LAST_ANSWER_CHARS else flat[:LAST_ANSWER_CHARS] + " …"
