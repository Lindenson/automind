"""A candidate checked against what the person said before it is proposed (spec 013 S2, I2 "verification").

`verify(candidate, car)` compares the make, the model (the same name, its words inside the other, the class form or
the transliteration — never a look-alike), the generation the person named, a used car's year, and the engine they
named (displacement, power, fuel) with the candidate's. The first contradiction is returned with what the person
said and what the candidate has, so the question can name it ("you wrote C-Class, I found only the E-Class"); a
contradicted candidate is never proposed. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from automind.chat.domain.case import CaseCar
from automind.chat.domain.identification.variant_match import VariantFacts, engine_of_fits
from automind.shared.vehicle import identity
from automind.shared.vehicle.model_names import match_model

YEAR_TOLERANCE = 1  # a used car's year may sit one year outside the generation's span (model years)


class Fact(StrEnum):
    """What the person said that a candidate can contradict."""

    MAKE = "MAKE"
    MODEL = "MODEL"
    GENERATION = "GENERATION"
    YEAR = "YEAR"
    ENGINE = "ENGINE"


@dataclass(frozen=True)
class Contradiction:
    """The candidate has `candidate_has` where the person said `person_said`."""

    fact: Fact
    person_said: str
    candidate_has: str


@dataclass(frozen=True)
class Verdict:
    """`ok` when nothing contradicts the person; else the first `contradiction`."""

    contradiction: Contradiction | None = None

    @property
    def ok(self) -> bool:
        """Nothing the person said is contradicted."""
        return self.contradiction is None


def verify(candidate: VariantFacts, car: CaseCar) -> Verdict:
    """The candidate checked against the car's facts in order: make, model, generation, year (used), engine."""
    for check in (_make, _model, _generation, _year, _engine):
        if (c := check(candidate, car)) is not None:
            return Verdict(c)
    return Verdict()


def same_model_name(said: str, found: str) -> bool:
    """The candidate's model is the model the person named: one names the other by the person's-words rules (exact,
    whole words, class form, transliteration; "Seal U" is the model of "Seal U DM-i")."""
    return match_model(said, [found]) is not None or match_model(found, [said]) is not None


def _make(v: VariantFacts, car: CaseCar) -> Contradiction | None:
    said, has = _plain(car.make), _plain(v.make)
    if said and has and not (said.startswith(has) or has.startswith(said)):  # "mercedes" names "mercedes-benz"
        return Contradiction(Fact.MAKE, car.make or "", v.make)
    return None


def _model(v: VariantFacts, car: CaseCar) -> Contradiction | None:
    if car.model and v.model and not same_model_name(car.model, v.model):
        return Contradiction(Fact.MODEL, car.model, v.model)
    return None


def _generation(v: VariantFacts, car: CaseCar) -> Contradiction | None:
    said, has = car.constraints.generation_hint, v.generation
    a, b = _plain(said), _plain(has)
    if a and b and a not in b and b not in a:  # "150" names "J150"; "Mk8" never "Mk7"
        return Contradiction(Fact.GENERATION, said or "", has or "")
    return None


def _year(v: VariantFacts, car: CaseCar) -> Contradiction | None:
    lo, hi = v.generation_years_from, v.generation_years_to
    if car.condition != "USED" or car.year is None or car.year_assumed or lo is None:
        return None
    if identity.generation_matches(car.year, lo, hi, YEAR_TOLERANCE):
        return None
    return Contradiction(Fact.YEAR, str(car.year), f"{v.generation or v.model} {lo}–{hi or ''}".strip("– "))


def _engine(v: VariantFacts, car: CaseCar) -> Contradiction | None:
    hint = car.constraints.engine_hint
    if hint is None or hint.empty() or engine_of_fits(v, hint):
        return None
    return Contradiction(Fact.ENGINE, hint.text() or hint.evidence, v.variant_name)


def _plain(s: str | None) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())
