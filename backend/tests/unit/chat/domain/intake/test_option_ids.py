"""Spec 013 T013: a tapped chip is applied by its option id, never by its words; chips carry the ids."""

from __future__ import annotations

from automind.chat.application.services.interpretation.ask import intake_quick_replies
from automind.chat.domain.case import CaseCar, CaseFile, Pending
from automind.chat.domain.intake import OptionKind, option_id, pick_by_id

ENGINES = [{"label": "E 200", "level": "ENGINE", "engine": "E 200", "fuel": "mhev", "power_kw": 150},
           {"label": "E 220 d", "level": "ENGINE", "engine": "E 220 d", "fuel": "mhev", "power_kw": 145}]  # fmt: skip
LABELS = {"new": "Новые", "used": "Подержанные", "choose": "Выбери сам", "remove": "Убрать {car}", "yes": "Да",
          "no": "Нет", "automatic": "Автомат", "manual": "Механика", "other": "Другая"}  # fmt: skip


def _case() -> CaseFile:
    items = [{"car": "car#1", "kind": "ENGINE", "item": "ENGINE", "choices": ENGINES},
             {"car": None, "kind": "CONDITION", "item": "CONDITION"}]  # fmt: skip
    car = CaseCar(key="car#1", request_text="Mercedes E", make="Mercedes-Benz", model="E-Class")
    return CaseFile(cars=[car], pending=Pending(kind="QUESTIONS", items=items))


def test_the_second_engine_is_applied_by_its_id() -> None:
    new, log = pick_by_id(_case(), option_id(OptionKind.CHOICE, "car#1", "ENGINE", 1)) or (None, [])
    assert new is not None and new.car("car#1").constraints.version_hint == "E 220 d"
    assert log == ["car#1: E 220 d (picked)"]


def test_condition_remove_and_gearbox_ids() -> None:
    new, _ = pick_by_id(_case(), "condition:USED") or (None, [])
    assert new is not None and new.car("car#1").condition == "USED"
    new, _ = pick_by_id(_case(), "remove:car#1") or (None, [])
    assert new is not None and new.cars == []
    new, _ = pick_by_id(_case(), "gb:car#1:manual") or (None, [])
    assert new is not None and new.car("car#1").constraints.gearbox_hint == "manual"


def test_an_id_that_no_longer_fits_is_not_applied() -> None:
    for oid in ("q:car#1:ENGINE:9", "q:car#2:ENGINE:0", "q:car#1:GEARBOX:0", "remove:car#3", "no:car#1", "bogus"):
        assert pick_by_id(_case(), oid) is None, oid


def test_chips_carry_their_ids() -> None:
    case = _case()
    chips = intake_quick_replies(list(case.pending.items), case, LABELS)  # type: ignore[union-attr]
    ids = {c["label"]: c.get("id") for c in chips}
    assert ids["E 200"] == "q:car#1:ENGINE:0" and ids["E 220 d"] == "q:car#1:ENGINE:1"
    assert ids["Новые"] == "condition:NEW" and ids["Выбери сам"] == "choose"
    assert ids["Убрать Mercedes-Benz E-Class"] == "remove:car#1"
