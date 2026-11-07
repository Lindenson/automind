"""The interpretation service's contract (spec 012 S9c): what `read` and `apply` give back, including the failure
paths — a model answer that cannot be read is asked back, never guessed; a car edit or a delta for a car the case does
not have applies nothing and asks which car."""

from __future__ import annotations

from typing import TypeVar

import pytest
from pydantic import BaseModel

from automind.chat.application.services.interpretation import (
    ApplyRequest,
    Interpretation,
    InterpretationService,
    Preset,
)
from automind.chat.dialog.prompts import load_all
from automind.chat.dialog.report_wording import WORDING
from automind.chat.domain.case import CaseCar, CaseDelta, CaseFile
from automind.delivery.bootstrap import reference

T = TypeVar("T", bound=BaseModel)
REF = reference(load_all())


class _LLM:
    """Answers the interpreter with a fixed result, or fails to validate (`answer` None)."""

    def __init__(self, answer: dict[str, object] | None) -> None:
        self.answer = answer

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        if self.answer is None:
            raise ValueError("the model's output does not validate")
        return schema.model_validate(self.answer)

    async def text(self, role: str, system: str, user: str) -> str:
        return ""


class _Log:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, str | None]] = []

    async def __call__(self, kind: str, car_key: str | None = None, item: str | None = None, **details: object) -> None:
        self.events.append((kind, car_key, item))


def _service(answer: dict[str, object] | None = None) -> tuple[InterpretationService, _Log]:
    log = _Log()
    return InterpretationService(_LLM(answer), REF, WORDING, log), log  # type: ignore[arg-type]  # a fake LLM


def _case() -> CaseFile:
    return CaseFile(cars=[CaseCar(key="car#1", request_text="SEAT Ateca", make="SEAT", model="Ateca")], next_car_no=2)


async def test_an_unreadable_model_answer_is_asked_back() -> None:
    service, _ = _service(answer=None)
    reading = await service.read(_case(), [], "something odd", None)
    assert reading.ask == "rephrase" and reading.interpretation is None
    assert reading.to_state("Please rephrase") == {"action": "ASK", "done": True, "reply_text": "Please rephrase"}


async def test_a_model_answer_naming_an_unknown_car_is_asked_back() -> None:
    service, _ = _service({"request": "correction", "language": "en", "delta": {"remove_cars": ["car#9"]}})
    assert (await service.read(_case(), [], "drop the other one", None)).ask == "rephrase"


async def test_a_button_needs_no_model() -> None:
    service, _ = _service(answer=None)  # the model would fail: it is not called
    button: Preset = {"kind": "research_more", "focus_cars": ["car#1"]}
    reading = await service.read(_case(), [{"role": "user", "text": "сравни"}], "", button)
    assert reading.interpretation is not None and reading.interpretation.request == "research_more"
    assert reading.language == "ru" and reading.interpretation.focus_cars == ["car#1"]


async def test_a_car_edit_is_built_by_code_and_logged() -> None:
    service, log = _service(answer=None)
    reading = await service.read(_case(), [], "", {"kind": "car_edit", "car_key": "car#1", "field": "remove"})
    assert reading.interpretation is not None and reading.interpretation.delta.remove_cars == ["car#1"]
    assert log.events == [("CARD_EDITED", "car#1", "remove")]


async def test_an_edit_of_an_unknown_car_asks_which_car_and_logs_nothing() -> None:
    service, log = _service(answer=None)
    reading = await service.read(_case(), [], "", {"kind": "car_edit", "car_key": "car#7", "field": "remove",
                                                   "language": "es"})  # fmt: skip
    assert reading.ask == "which_car" and not log.events
    assert reading.to_state("¿Qué coche?") == {"action": "ASK", "done": True, "reply_text": "¿Qué coche?",
                                               "language": "es"}  # fmt: skip


def test_a_delta_for_an_unknown_car_applies_nothing() -> None:
    service, _ = _service()
    i = Interpretation(request="correction", language="en", delta=CaseDelta(remove_cars=["car#7"]))
    applied = service.apply(ApplyRequest(_case(), i, "remove it", picked=False, year=2026))
    assert applied.ask == "which_car" and applied.case == _case() and not applied.saved


def test_an_applied_message_says_what_changed() -> None:
    service, _ = _service()
    i = Interpretation(request="compare", language="en")
    applied = service.apply(ApplyRequest(_case(), i, "I live in the south of Spain", picked=False, year=2026))
    assert applied.saved and applied.case.profile.region_code == "SOUTH"
    state = applied.to_state(5)
    assert state["case_version"] == 5 and state["case_changed"] is True and state["persona_changed"] is False
    assert applied.to_state(None) == {"not_understood": [], "request_kind": "compare", "case_changed": False}


@pytest.mark.parametrize("text", ["any", "любой", "cualquiera"])
def test_choose_for_me_settles_the_request(text: str) -> None:
    service, _ = _service()
    applied = service.apply(ApplyRequest(_case(), Interpretation(request="compare", language="en"), text, False, 2026))
    assert applied.request == "choose_for_me"
