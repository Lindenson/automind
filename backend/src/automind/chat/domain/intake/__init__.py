"""Chat · chat.domain.intake: the intake loop — which question to ask next about the cars, ranking a make's
line-up for the person, applying the option they picked, and keeping their own model names. Pure.

Owns: `steps` — the step machine (ASK, PROPOSE, REMOVE_OR_CHOOSE, CARD, NONE) and never-repeated questions;
  `lineup` — body words, line-up ranking and candidates with machine reasons (FR-008, spec 007 US7);
  `pick` — applying a picked option (choice, level, "choose for me", inherited condition);
  `names` — the person's own model names kept (never "nearest: <the same model>").
Depends on: chat.domain.case, chat.domain.understanding, shared.vehicle. Must not depend on: sqlalchemy, langgraph,
  fastapi, the application, the dialog.
Note: `steps` moves into chat.dialog with the policy in S6 (it is the intake part of the dialog state machine).
Public API: the names below (`from automind.chat.domain import intake; intake.next_step(...)`).
"""

from automind.chat.domain.intake.lineup import (
    BODY_WORDS,
    LineupModel,
    body_class_of,
    body_of,
    pick_candidates,
    rank_lineup,
)
from automind.chat.domain.intake.names import (
    keep_user_names,
    other_names,
    same_name,
    user_model,
)
from automind.chat.domain.intake.pick import (
    inherit_condition,
    pick,
)
from automind.chat.domain.intake.steps import (
    ALL,
    MAX_ITEMS,
    Limits,
    Step,
    StepItem,
    StepKind,
    identity_key,
    is_repeat,
    next_step,
    progress,
    question_hash,
    record_asked,
)

__all__ = [
    "ALL",
    "BODY_WORDS",
    "Limits",
    "LineupModel",
    "MAX_ITEMS",
    "Step",
    "StepItem",
    "StepKind",
    "body_class_of",
    "body_of",
    "identity_key",
    "inherit_condition",
    "is_repeat",
    "keep_user_names",
    "next_step",
    "other_names",
    "pick",
    "pick_candidates",
    "progress",
    "question_hash",
    "rank_lineup",
    "record_asked",
    "same_name",
    "user_model",
]
