"""The person's rejections as identification applies them (spec 013 S2, T022): the facts of each kind of candidate —
a sourced version, a catalogue row or version, a choice of the card, a line-up model, a model name — for the one
domain filter `rejection.exclude_rejected`. Every strategy and every list of options goes through it, so a rejected
candidate is never proposed or offered again."""

from __future__ import annotations

from collections.abc import Sequence

from automind.chat.application.services.identification.contracts import VariantRow
from automind.chat.domain.case import CaseCar, Choice
from automind.chat.domain.identification import ladder
from automind.chat.domain.identification.rejection import CandidateFacts, exclude_rejected, is_rejected
from automind.chat.domain.identification.variant_match import VariantFacts
from automind.chat.domain.intake import LineupModel


def version_facts(v: ladder.Version) -> CandidateFacts:
    """A sourced (or catalogued) version of the ladder: its engine, gearboxes and driven wheels."""
    return CandidateFacts(names=(v.engine,), gearboxes=v.gearboxes, drives=v.drives)


def row_facts(row: VariantRow) -> CandidateFacts:
    """A catalogue row as the policy and the card keep it."""
    return CandidateFacts(model=row["model"], generation=row["generation"],
                          names=(row["label"], row["variant_name"]), gearboxes=_one(row["transmission"]),
                          drives=_one(row["drive"]))  # fmt: skip


def variant_facts(v: VariantFacts) -> CandidateFacts:
    """A catalogue version (the resolver's answer, a version proposed)."""
    return CandidateFacts(model=v.model, generation=v.generation, names=(v.label, v.variant_name),
                          gearboxes=_one(v.transmission), drives=_one(v.drive))  # fmt: skip


def choice_facts(c: Choice) -> CandidateFacts:
    """A choice of the card: a model, a catalogue version (its label) or a ladder option (engine, gearbox, drive)."""
    names = tuple(n for n in (c.engine, c.label if c.variant_id else None) if n)
    return CandidateFacts(model=c.model, names=names, gearboxes=_one(c.gearbox), drives=_one(c.drive))


def name_facts(name: str) -> CandidateFacts:
    """A version named by its words only (the resolver's alternatives)."""
    return CandidateFacts(names=(name,))


def model_facts(name: str) -> CandidateFacts:
    """A model name (a known model, a "did you mean" suggestion)."""
    return CandidateFacts(model=name)


def lineup_facts(m: LineupModel) -> CandidateFacts:
    """A model of a make's line-up."""
    return CandidateFacts(model=m.model)


def without_rejected_choices(car: CaseCar, choices: Sequence[Choice]) -> list[Choice]:
    """The choices the person has not rejected for this car."""
    return exclude_rejected(choices, car.identity_rejected, choice_facts)


def without_rejected_models(car: CaseCar, names: Sequence[str]) -> list[str]:
    """The model names the person has not rejected for this car."""
    return exclude_rejected(names, car.identity_rejected, model_facts)


def generation_rejected(car: CaseCar, generation: str | None) -> bool:
    """The person rejected this generation of the car."""
    return is_rejected(CandidateFacts(generation=generation), car.identity_rejected)


def _one(value: str | None) -> tuple[str, ...]:
    return (value,) if value else ()
