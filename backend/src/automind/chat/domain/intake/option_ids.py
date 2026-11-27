"""Option ids of the one-tap answers (spec 013 T013): a chip under a question carries an id that names what it
answers, and a tapped chip is applied by that id — never by guessing from its words.

Ids: `q:<car>:<kind>:<n>` the n-th option of the car's question; `gb:<car>:<automatic|manual>` a gearbox;
`condition:<NEW|USED>` new or used for every car; `remove:<car>`; `choose` (let the hub choose); `yes:<car>` /
`no:<car>` to a proposal. An id that no longer fits the pending question (or `no:`, which needs the person's words)
is not applied here: the chip's text is then read like typed words (old clients send only the text).
"""

from __future__ import annotations

from enum import StrEnum

from automind.chat.domain.case import CaseFile, Choice
from automind.chat.domain.case.enums import Condition, Gearbox
from automind.chat.domain.intake.pick import apply_choice, pick


class OptionKind(StrEnum):
    """What a chip answers."""

    CHOICE = "q"
    GEARBOX = "gb"
    CONDITION = "condition"
    REMOVE = "remove"
    CHOOSE = "choose"
    YES = "yes"
    NO = "no"


# Question kinds about one car (a chip removes the car) and those that take "choose for me" (ENGINE only with options)
CAR_KINDS = ("CAR_IDENTITY", "MAKE_LINEUP", "UNKNOWN_MODEL", "ENGINE", "USED_AGE", "TRIM", "GEARBOX", "PROPOSE",
             "REMOVE_OR_CHOOSE", "FUEL", "POWER", "DRIVE")  # fmt: skip
CHOOSABLE_KINDS = ("MAKE_LINEUP", "TRIM", "GEARBOX", "REMOVE_OR_CHOOSE", "FUEL", "POWER", "DRIVE")

GEARBOXES: dict[str, Gearbox] = {"automatic": "automatic", "manual": "manual"}
CONDITIONS: dict[str, Condition] = {"NEW": "NEW", "USED": "USED"}


def option_id(kind: OptionKind, *parts: str | int) -> str:
    """The id of a chip: its kind and what it points at."""
    return ":".join([kind.value, *(str(p) for p in parts)])


def pick_by_id(case: CaseFile, oid: str) -> tuple[CaseFile, list[str]] | None:
    """(the case with the tapped option applied, the change log), or None when the id does not fit the case as it is
    now (then the chip's words are read instead)."""
    head, _, rest = oid.partition(":")
    try:
        kind = OptionKind(head)
    except ValueError:
        return None
    if kind is OptionKind.CHOOSE:
        return pick(case, kind.value, gearbox_words={}, choose=True)
    if kind is OptionKind.YES:
        return pick(case, kind.value, gearbox_words={}, yes=True)
    if kind is OptionKind.CONDITION:
        return _condition(case, rest)
    if kind is OptionKind.REMOVE:
        return _remove(case, rest)
    if kind is OptionKind.GEARBOX:
        return _gearbox(case, rest)
    if kind is OptionKind.CHOICE:
        return _choice(case, rest)
    return None  # NO: what the person wants instead is in their words


def _condition(case: CaseFile, value: str) -> tuple[CaseFile, list[str]] | None:
    condition = CONDITIONS.get(value)
    if condition is None:
        return None
    new = case.model_copy(deep=True)
    for car in new.cars:
        if car.condition == "UNKNOWN":
            car.condition = condition
    return new, [f"condition: {value.lower()} (picked)"]


def _remove(case: CaseFile, key: str) -> tuple[CaseFile, list[str]] | None:
    if not any(c.key == key for c in case.cars):
        return None
    new = case.model_copy(deep=True)
    new.cars = [c for c in new.cars if c.key != key]
    return new, [f"{key} removed"]


def _gearbox(case: CaseFile, rest: str) -> tuple[CaseFile, list[str]] | None:
    key, _, name = rest.rpartition(":")
    gearbox = GEARBOXES.get(name)
    if gearbox is None or not any(c.key == key for c in case.cars):
        return None
    new = case.model_copy(deep=True)
    new.car(key).constraints.gearbox_hint = gearbox
    return new, [f"{key}: gearbox {gearbox}"]


def _choice(case: CaseFile, rest: str) -> tuple[CaseFile, list[str]] | None:
    """The n-th option of the car's pending question, when that question is still open."""
    key, kind, n = (rest.split(":") + ["", "", ""])[:3]
    p = case.pending
    if p is None or not n.isdigit():
        return None
    item = next((it for it in p.items if str(it.get("car") or "") == key and it.get("kind") == kind), None)
    raw = (item or {}).get("choices")
    if not isinstance(raw, list) or int(n) >= len(raw):
        return None
    new = case.model_copy(deep=True)
    return new, [apply_choice(new.car(key), Choice.model_validate(raw[int(n)]))]
