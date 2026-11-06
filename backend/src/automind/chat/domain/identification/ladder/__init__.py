"""Chat · chat.domain.identification.ladder: the identification ladder (spec 008) — a car is narrowed level by level
(generation, fuel, engine, gearbox, power) over the versions really sold, one question at a time. Pure.

Owns: `model` — levels, Version/Generation, Wanted/Narrowed; `narrow` — the versions left for what the person said;
  `steps` — the next question, applying a picked option, the decision; `labels` — reconcile and the labels shown.
Flow: versions sold + Wanted → narrow → steps.next_step (ask) / steps.decide (identified) → labels for the card.
Depends on: chat.domain.case, shared.vehicle. Must not depend on: sqlalchemy, the application, the dialog.
Public API: the names below (`from automind.chat.domain.identification import ladder; ladder.decide(...)`).
"""

from automind.chat.domain.identification.ladder.labels import (
    Reconciled,
    reconcile,
    registered_label,
    status_line,
    years_text,
)
from automind.chat.domain.identification.ladder.model import (
    AUTO_GEARBOXES,
    GEARBOX_LABEL,
    IMPLIED_FUEL,
    ITEM,
    ITEMS,
    MAX_OPTIONS,
    ORDER,
    POWERTRAIN,
    Generation,
    Level,
    Narrowed,
    Origin,
    StepKind,
    Version,
    Wanted,
    cv_label,
    family_word,
    line_of,
    version_of_json,
    version_to_json,
    wanted_of,
)
from automind.chat.domain.identification.ladder.narrow import (
    narrow,
    on_sale,
    sold_in,
    sold_until,
    stale,
    without,
)
from automind.chat.domain.identification.ladder.steps import (
    Auto,
    Decision,
    Option,
    Step,
    apply_option,
    decide,
    levels_of,
    next_step,
)

__all__ = [
    "AUTO_GEARBOXES",
    "Auto",
    "Decision",
    "GEARBOX_LABEL",
    "Generation",
    "IMPLIED_FUEL",
    "ITEM",
    "ITEMS",
    "Level",
    "MAX_OPTIONS",
    "Narrowed",
    "ORDER",
    "Option",
    "Origin",
    "POWERTRAIN",
    "Reconciled",
    "Step",
    "StepKind",
    "Version",
    "Wanted",
    "apply_option",
    "cv_label",
    "decide",
    "family_word",
    "levels_of",
    "line_of",
    "narrow",
    "next_step",
    "on_sale",
    "reconcile",
    "registered_label",
    "sold_in",
    "sold_until",
    "stale",
    "status_line",
    "version_of_json",
    "version_to_json",
    "wanted_of",
    "without",
    "years_text",
]
