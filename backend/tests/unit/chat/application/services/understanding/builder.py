"""Shared pieces of the understanding tests: a case, open questions, a fake model, the phrases' language words."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.chat.application.services.understanding.rules import Context
from automind.chat.dialog import phrases
from automind.chat.domain.case import CaseCar, CaseFile, Pending
from automind.chat.domain.understanding.intent import Understanding
from automind.chat.domain.understanding.open_question import OpenQuestion, open_question

CASE = CaseFile(cars=[CaseCar(key="car#1", request_text="Kia Sportage", make="Kia", model="Sportage"),
                      CaseCar(key="car#2", request_text="Mercedes C", make="Mercedes-Benz", model="E-Class")],
                next_car_no=3)  # fmt: skip
ENGINES = [{"label": "1.6 T-GDi HEV"}, {"label": "1.6 CRDi"}]
ENGINE_Q = Pending(kind="QUESTIONS", items=[{"kind": "ENGINE", "car": "car#1", "text": "Which engine?",
                                             "choices": ENGINES}])  # fmt: skip
CARD = Pending(kind="CONFIRM_INTAKE", items=[{"car": "car#1"}, {"car": "car#2"}])


def question(p: Pending) -> OpenQuestion:
    q = open_question(p)
    assert q is not None
    return q


class Words:
    """The dialog's language words (the real `phrases`)."""

    def stable_language(self, detected: str | None, current: str, earlier: list[str]) -> str | None:
        return phrases.stable_language(detected, current, earlier)

    def guess_language(self, texts: list[str]) -> str:
        return phrases.guess_language(texts)


class Makes:
    """Two makes the safety net knows."""

    def match_make(self, text: str) -> str | None:
        return {"kia": "Kia", "seat": "SEAT", "bmw": "BMW"}.get(text.strip().lower())


def ctx(case: CaseFile = CASE, p: Pending | None = None, text: str = "", earlier: list[str] | None = None) -> Context:
    return Context(case, question(p) if p else None, text, earlier or [], Words(), Makes())  # type: ignore[arg-type]


def understanding(**fields: Any) -> Understanding:
    return Understanding.model_validate({"language": "ru", **fields})


@dataclass
class FakeLLM:
    """Returns `out` for the understander role (or raises it); records the prompts it was given."""

    out: Understanding | Exception
    prompts: list[str] = field(default_factory=list)

    async def structured(self, role: str, schema: type, system: str, user: str) -> Understanding:
        assert role == "understander" and schema is Understanding
        self.prompts.append(user)
        if isinstance(self.out, Exception):
            raise self.out
        return self.out

    async def text(self, role: str, system: str, user: str) -> str:
        raise AssertionError("the understander makes one structured call")
