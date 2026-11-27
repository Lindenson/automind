"""The tactic of the next identification attempt after the person rejected something (spec 013 S2, T024; I4 "no
circles" in its first form, before the S5 repeat guard).

After a rejection the same path must not end where it ended before: when the attempt finds nothing to offer, or asks
exactly the question asked last time (same level, same options), the tactic widens — the make's other models, the
sources that were checked, a link asked for — instead of asking it again. Pure: the application builds the wider
question.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from automind.chat.domain.case import IdentifyKind, IdentifyOutcome, IntakeItem
from automind.chat.domain.identification.rejection import Rejection

FOUND: IdentifyKind = "IDENTIFIED"
NOT_FOUND: IdentifyKind = "NOT_FOUND"
OPEN_NEEDS: frozenset[IntakeItem] = frozenset({"MODEL", "ENGINE", "CHOICE"})  # nothing to offer here is a dead end


class Tactic(StrEnum):
    """KEEP the attempt's outcome, or WIDEN the search and say what was checked."""

    KEEP = "KEEP"
    WIDEN = "WIDEN"


@dataclass(frozen=True)
class Asked:
    """A question of the identification as the person sees it: what it asks and the options offered."""

    need: str | None
    level: str | None
    options: tuple[str, ...]

    @classmethod
    def of(cls, o: IdentifyOutcome | None) -> Asked | None:
        """The question an outcome asks (None: nothing asked, the car was identified)."""
        if o is None or o.outcome == FOUND:
            return None
        return cls(o.need, o.level, tuple(sorted(c.label for c in o.choices)))


def after_rejection(rejected: Sequence[Rejection], before: IdentifyOutcome | None, found: IdentifyOutcome) -> Tactic:
    """WIDEN when the car has a rejection and this attempt is a dead end (nothing found, nothing to offer) or asks
    the very question asked before; KEEP otherwise (no rejection, a version found, or a new question)."""
    if not rejected or found.outcome == FOUND:
        return Tactic.KEEP
    if dead_end(found):
        return Tactic.WIDEN
    asked = Asked.of(found)
    return Tactic.WIDEN if asked is not None and asked == Asked.of(before) else Tactic.KEEP


def dead_end(o: IdentifyOutcome) -> bool:
    """The attempt found nothing and has nothing to offer about the model or the version."""
    return o.outcome == NOT_FOUND or (not o.choices and o.need in OPEN_NEEDS)
