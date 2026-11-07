"""Stage settle: the outcome is recorded on the car with the key of the facts it was identified from, so the same
facts are not identified again (spec 005 R1)."""

from __future__ import annotations

import hashlib

from automind.chat.domain import intake
from automind.chat.domain.case import CaseCar, IdentifyOutcome
from automind.chat.domain.case.enums import Resolution

SETTLED = ("CONFIRMED", "AUTO_OK", "PROPOSED")  # a version is set: the person confirms or changes it


def key_of(car: CaseCar) -> str:
    """The key of the facts a car is identified from (same facts, same key)."""
    return hashlib.sha1(repr(intake.identity_key(car)).encode()).hexdigest()[:12]


def needs_identify(car: CaseCar) -> bool:
    """Run the identify step for this car? Not for a car identified with the same facts, nor for a car confirmed
    before spec 005 (no outcome recorded)."""
    o = car.identify
    if o is None:
        return not (car.variant_id and car.resolution in ("CONFIRMED", "AUTO_OK"))
    return o.outcome != "IDENTIFIED" or o.key != key_of(car)


def has_version(car: CaseCar) -> bool:
    """A version is set (found earlier, confirmed or proposed): nothing to ask about the identity."""
    return bool(car.variant_id) and car.resolution in SETTLED


def settle(car: CaseCar, o: IdentifyOutcome) -> IdentifyOutcome:
    """Record the outcome on the car with the key of its facts; returns the outcome."""
    o.key = key_of(car)
    car.identify = o
    return o


def proposed(car: CaseCar) -> Resolution:
    """A version the hub found is proposed; after "choose for me" it is taken (no second question)."""
    return "CONFIRMED" if car.chosen_for_me else "PROPOSED"
