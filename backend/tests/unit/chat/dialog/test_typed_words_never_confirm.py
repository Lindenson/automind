"""Spec 013 T012: on the intake card and the variants proposal only a button confirms; typed words — "нет",
"нет, другую", "да, но дизель" — go to the interpreter, and no car is confirmed by them."""

from __future__ import annotations

import pytest

from automind.chat.dialog.nodes import confirm
from automind.chat.domain.case import CaseFile, Pending
from automind.chat.domain.intake import CardChoice, card_answer

from .test_confirm_variants_cost import Store, _car, _case, _runtime

TYPED = ["нет", "нет, другую", "да, но дизель", "yes", "да"]


def _card_case() -> CaseFile:
    return CaseFile(cars=[_car(variant_id="v1", label="S9 Cx", resolution="PROPOSED")],
                    pending=Pending(kind="CONFIRM_INTAKE", items=[{"car": "car#1"}]))  # fmt: skip


def _variants_case() -> CaseFile:
    return CaseFile(cars=[_car(variant_id="v1", label="S9 Cx", resolution="PROPOSED")],
                    pending=Pending(kind="CONFIRM_VARIANTS", items=[{"car": "car#1"}]))  # fmt: skip


@pytest.mark.parametrize("words", TYPED)
async def test_typed_words_on_the_card_are_read_never_confirm(words: str) -> None:
    store = Store()
    out = await confirm.apply_intake({"resume": {"choice": "", "text": words}}, _runtime(store, _card_case()))  # type: ignore[arg-type]
    assert (out["route"], out["user_text"]) == ("interpret", words)
    case = _case(store)
    assert case.car("car#1").resolution == "PROPOSED" and not case.intake.card_confirmed


@pytest.mark.parametrize("words", TYPED)
async def test_typed_words_on_the_proposal_are_read_never_confirm(words: str) -> None:
    store = Store()
    out = await confirm.apply_variants({"resume": {"choice": "text", "text": words}}, _runtime(store, _variants_case()))  # type: ignore[arg-type]
    assert (out["route"], out["user_text"]) == ("interpret", words)
    assert _case(store).car("car#1").resolution == "PROPOSED"


async def test_an_unknown_button_id_never_confirms() -> None:
    store = Store()
    out = await confirm.apply_variants({"resume": {"choice": "maybe"}}, _runtime(store, _variants_case()))  # type: ignore[arg-type]
    assert out["route"] == "interpret" and _case(store).car("car#1").resolution == "PROPOSED"


async def test_the_yes_button_confirms_and_not_now_keeps_the_cars() -> None:
    store = Store()
    out = await confirm.apply_intake({"resume": {"choice": "yes"}, "language": "en"}, _runtime(store, _card_case()))  # type: ignore[arg-type]
    assert out["cost_approved"] and _case(store).car("car#1").resolution == "CONFIRMED"
    store = Store()
    out = await confirm.apply_intake({"resume": {"choice": "stop"}, "language": "en"}, _runtime(store, _card_case()))  # type: ignore[arg-type]
    assert out["research_declined"] and _case(store).intake.card_confirmed


@pytest.mark.parametrize(("resume", "kind"), [
    ({"choice": "yes"}, CardChoice.CONFIRM), ({"choice": "stop"}, CardChoice.STOP),
    ({"choice": "option:car#1:v2"}, CardChoice.OPTION), ({"choice": "remove:car#2"}, CardChoice.REMOVE),
    ({"choice": "", "text": "нет"}, CardChoice.TEXT), ({"choice": "nope"}, CardChoice.OTHER),
])  # fmt: skip
def test_card_answer_kinds(resume: dict[str, str], kind: CardChoice) -> None:
    assert card_answer(resume).kind is kind
