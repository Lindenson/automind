"""Stage change_tactic (spec 013 S2, T024): after the person rejected something, an attempt that finds nothing or
would ask the same question again widens instead of asking it again. About the model: the make's other models
(catalogue and line-up, without what was rejected and without the model that was not found) and a notice that says
what was looked for, what was checked, and asks for a link. About the version: the options left, or — when none is
left — a notice that names what was rejected and asks for a link or the engine. The decision is the domain's
`tactic.after_rejection`."""

from __future__ import annotations

from automind.chat.application.services.identification.contracts import KnownModels
from automind.chat.application.services.identification.rejected import without_rejected_models
from automind.chat.application.services.identification.stages.settle import settle
from automind.chat.domain.case import CaseCar, Choice, IdentifyOutcome, IntakeItem
from automind.chat.domain.identification.rejection import RejectLevel, same_value
from automind.chat.domain.identification.tactic import Tactic, after_rejection

MAX_MODELS = 8  # the make's models offered when the search widens
# the notices (dialog phrases): the model not found (with the sources checked, or without), no other version left
CHECKED_EVENT, WIDER_EVENT, NO_VERSION_EVENT = "not_found_checked", "not_found_wider", "version_not_found"


def change_tactic(car: CaseCar, before: IdentifyOutcome | None, found: IdentifyOutcome,
                  names: KnownModels) -> IdentifyOutcome:  # fmt: skip
    """`found` as it is, or the wider question when the domain says WIDEN (`before`: the car's outcome before this
    attempt). Pure apart from recording the outcome on the car (`settle`)."""
    if after_rejection(car.identity_rejected, before, found) is Tactic.KEEP:
        return found
    if found.need in (None, "MODEL"):
        models = _models(car, names)
        choices = [Choice(label=f"{car.make} {m}", make=car.make, model=m, reason="wider") for m in models]
        return _settled(car, found, choices, "MODEL", _model_event(car, found))
    event = {"kind": NO_VERSION_EVENT, "rejected": ", ".join(_versions_rejected(car))}
    return _settled(car, found, found.choices, found.need, event)


def _models(car: CaseCar, names: KnownModels) -> list[str]:
    """The make's known models without the rejected ones and without the model that was just not found."""
    left = without_rejected_models(car, sorted(names.known))
    return [m for m in left if not same_value(m, car.model)][:MAX_MODELS]


def _model_event(car: CaseCar, found: IdentifyOutcome) -> dict[str, str]:
    wanted = next((r.wanted for r in reversed(car.identity_rejected) if r.wanted), None)
    wanted = wanted or " ".join(x for x in (car.make, car.model) if x) or car.request_text
    checked = ", ".join(found.checked)
    return {"kind": CHECKED_EVENT, "wanted": wanted, "checked": checked} if checked else {
        "kind": WIDER_EVENT, "wanted": wanted}  # fmt: skip


def _versions_rejected(car: CaseCar) -> list[str]:
    return [r.value for r in car.identity_rejected if r.level is not RejectLevel.MODEL]


def _settled(car: CaseCar, found: IdentifyOutcome, choices: list[Choice], need: IntakeItem | None,
             event: dict[str, str]) -> IdentifyOutcome:  # fmt: skip
    o = found.model_copy(update={"outcome": "CHOICES" if choices else "NOT_FOUND", "need": need,
                                 "level": found.level if need == found.need else None, "choices": choices,
                                 "events": [*found.events, event]})  # fmt: skip
    return settle(car, o)
