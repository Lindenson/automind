"""One turn's understanding as stored (spec 013 T033, understanding-spec §7): plain data the `UnderstandingLog`
port writes and reads back, enough to say "the person wrote X → the model read Y → code dropped Z and corrected W →
the intent was I". The policy's passes of the same turn are spec 015's `policy_decisions`, joined by `turn_id`.

During the shadow (S3) the old interpreter decides; `old_reading` keeps what it read, so both can be compared."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from automind.chat.domain.understanding.intent import IntentSource, Override
from automind.shared.contracts.json import JsonObject


class Dropped(BaseModel):
    """Something a check took out of the model's reading: the check, the field, and why ("budget 50000 is not in
    the message")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    field: str
    why: str


class UnderstandingRecord(BaseModel):
    """The understanding of one turn; `turn_id` is its key (a retried node writes the same row again)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chat_id: str
    turn_id: str
    source: IntentSource
    input: JsonObject  # {"text": …} or {"ui": UiAction}, and the open question ({"question": OpenQuestion | None})
    open_question_id: str | None = None
    question_repeated: bool = False  # the same question was open at the start of the chat's previous turn too
    model: str | None = None  # the model that answered (None: no model call — a button, or the call failed)
    prompt_version: str | None = None  # "understander@v1"
    latency_ms: int | None = Field(default=None, ge=0)
    model_raw: JsonObject | None = None  # the `Understanding` as the model returned it
    refused: str | None = None  # the whole reading refused (a car the case does not have, the model failed)
    rejected: tuple[Dropped, ...] = ()
    overrides: tuple[Override, ...] = ()
    intent: JsonObject | None = None  # the resolved `Intent` (None when the reading was refused)
    old_reading: JsonObject | None = None  # S3 shadow: what the old interpreter read (it decided the turn)
