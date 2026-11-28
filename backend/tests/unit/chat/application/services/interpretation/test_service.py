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
from automind.chat.domain.case import CaseCar, CaseDelta, CaseFile, Pending
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


async def test_the_rephrase_question_keeps_the_persons_language() -> None:
    """Review 2026-11-27: a Russian person got "please rephrase" in English (the turn's language is reset to "en")."""
    service, _ = _service(answer=None)
    history = [{"role": "user", "text": "сравни сеат атеку и киа спортейдж"}, {"role": "assistant", "text": "…"}]
    assert (await service.read(_case(), history, "ну и что", None)).language == "ru"


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
    assert reading.ask == "which_car" and not log.events and reading.language == "es"


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
    assert applied.changes and not any(ch.startswith("persona:") for ch in applied.changes)
    assert applied.request == "compare" and applied.not_understood == []


@pytest.mark.parametrize("text", ["any", "любой", "cualquiera"])
def test_choose_for_me_settles_the_request(text: str) -> None:
    service, _ = _service()
    applied = service.apply(ApplyRequest(_case(), Interpretation(request="compare", language="en"), text, False, 2026))
    assert applied.request == "choose_for_me"


def _asked_case() -> CaseFile:
    choices = [
        {"label": "1.5 TSI", "level": "ENGINE", "engine": "1.5 TSI", "fuel": "petrol", "power_kw": 110},
        {"label": "2.0 TDI", "level": "ENGINE", "engine": "2.0 TDI", "fuel": "diesel", "power_kw": 110},
    ]
    case = _case()
    case.pending = Pending(kind="QUESTIONS", items=[{"car": "car#1", "kind": "ENGINE", "choices": choices}])
    return case


async def test_a_tapped_chip_is_applied_by_its_id_without_the_model() -> None:
    """Spec 013 T013: the chip's words ("1.5 TSI") would pick the first option; its id picks the second."""
    service, _ = _service(answer=None)  # the model is never asked
    preset: Preset = {"kind": "pick", "option_id": "q:car#1:ENGINE:1"}
    reading = await service.read(_asked_case(), [], "1.5 TSI", preset)
    assert reading.picked and reading.interpretation is not None
    req = ApplyRequest(_asked_case(), reading.interpretation, "1.5 TSI", True, 2026, "q:car#1:ENGINE:1")
    assert service.apply(req).case.car("car#1").constraints.version_hint == "2.0 TDI"


async def test_a_stale_chip_id_is_read_as_words() -> None:
    service, _ = _service({"request": "compare", "language": "en", "delta": {}})
    reading = await service.read(_case(), [], "1.5 TSI", {"kind": "pick", "option_id": "q:car#1:ENGINE:1"})
    assert not reading.picked and reading.interpretation is not None


def _bmw() -> CaseFile:
    car = CaseCar(key="car#2", request_text="БМВ 220д 2024 года", make="BMW", model="2 Series", condition="USED",
                  year=2024, mileage_km=30000)  # fmt: skip
    return CaseFile(cars=[car], next_car_no=3)


_NOT_THIS = {"kind": "car_edit", "car_key": "car#2", "field": "not_this_car", "value": "320 d"}


async def test_not_this_car_is_read_like_a_typed_car_and_keeps_the_purchase() -> None:
    """Spec 017 C1 (chat 725e7437): "320 d" on a BMW is the 3 Series with the 320d engine; year, mileage and
    condition the person gave stay; the words read are the make's ("BMW 320 d")."""
    said: list[str] = []
    bmw = {"request_text": "BMW 320 d", "make": "BMW", "model": "3 Series",
           "constraints": {"trim_hint": "320d", "fuel_hint": "diesel"}}  # fmt: skip
    service, log = _service({"request": "compare", "language": "ru", "delta": {"add_cars": [bmw]}})
    inner = service.llm.structured

    async def spy(role: str, schema: type[T], system: str, user: str) -> T:
        said.append(user)
        return await inner(role, schema, system, user)

    service.llm.structured = spy  # type: ignore[method-assign]
    reading = await service.read(_bmw(), [], "", _NOT_THIS)
    assert reading.interpretation is not None
    ctx = reading.interpretation.delta.replace_cars[0]
    assert (ctx.make, ctx.model, ctx.year, ctx.mileage_km, ctx.condition) == ("BMW", "3 Series", 2024, 30000, "USED")
    assert ctx.constraints is not None and ctx.constraints.fuel_hint == "diesel"
    assert any("BMW 320 d" in u for u in said) and log.events == [("CARD_EDITED", "car#2", "not_this_car")]
    applied = service.apply(ApplyRequest(_bmw(), reading.interpretation, "", picked=False, year=2026))
    car = applied.case.car("car#2")
    assert (car.model, car.year, car.mileage_km) == ("3 Series", 2024, 30000)


async def test_not_this_car_falls_back_to_the_words_when_the_reading_fails() -> None:
    service, _ = _service(answer=None)
    reading = await service.read(_bmw(), [], "", {**_NOT_THIS, "value": "BMW X3 2019"})
    assert reading.interpretation is not None
    ctx = reading.interpretation.delta.replace_cars[0]
    assert (ctx.make, ctx.model, ctx.year) == ("BMW", "X3 2019", 2024)  # code split: the words as the model


async def test_not_this_car_with_a_stated_year_takes_the_new_year() -> None:
    other = {"request_text": "Audi A4 2019", "make": "Audi", "model": "A4", "year": 2019, "condition": "USED"}
    service, _ = _service({"request": "compare", "language": "ru", "delta": {"add_cars": [other]}})
    reading = await service.read(_bmw(), [], "", {**_NOT_THIS, "value": "Audi A4 2019"})
    assert reading.interpretation is not None
    ctx = reading.interpretation.delta.replace_cars[0]
    assert (ctx.make, ctx.model, ctx.year, ctx.mileage_km) == ("Audi", "A4", 2019, 30000)
