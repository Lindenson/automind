"""The writer's check (spec 016 T305–T307): a contradiction gets one rewrite in the writer's role; a provider that is
down or a transient failure removes the sentence instead, any other error fails the turn; the answer runs the same
four rules as the report; a removal adds one quiet line in the person's language."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from automind.chat.application.services.report.contracts import CheckInput, Computed
from automind.chat.dialog.nodes.report_io import AnswerIn
from automind.chat.dialog.phrases import t
from automind.chat.dialog.report_writer import Writing, report_check, with_notice, write_answer
from automind.chat.domain.case import CaseCar, CaseFile
from automind.shared.contracts.provider_failure import ProviderUnavailable
from automind.shared.metering.usage import BudgetExceeded

CI = CheckInput(has_data=frozenset({"reliability_score"}), ties=frozenset({"boot_volume"}), tie=True,
                car_names=("Kia Sorento", "Toyota Land Cruiser Prado"))  # fmt: skip
TIE_WINNER = "Обе хороши, но лучший выбор — Prado."
FINE = "Обе машины близки."


@dataclass
class LLM:
    """Answers in order; an exception in the list is raised instead."""

    answers: list[Any]
    calls: list[str] = field(default_factory=list)

    async def text(self, role: str, system: str, user: str) -> str:
        self.calls.append(role)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return str(answer)


def _ctx(llm: LLM) -> Any:
    async def status(*a: Any, **k: Any) -> None:
        return None

    ports = SimpleNamespace(llm=llm, ref=SimpleNamespace(prompts={"answerer": "answer in {language}"}))
    return SimpleNamespace(ports=ports, chat_id="c", turn_id="t", status=status)


def _writing(role: str = "reporter") -> Writing:
    return Writing(role, "system", "request", {"facts": 1}, CI, set(), 2)


async def test_a_contradiction_is_rewritten_once_in_the_writers_role() -> None:
    llm = LLM([FINE])
    assert await report_check(_ctx(llm), _writing("answerer"), TIE_WINNER) == (FINE, 0)
    assert llm.calls == ["answerer"]


async def test_a_rewrite_that_still_contradicts_is_removed() -> None:
    assert await report_check(_ctx(LLM([TIE_WINNER])), _writing(), f"{TIE_WINNER} {FINE}") == ("", 1)


@pytest.mark.parametrize("error", [ProviderUnavailable("all models down"), RuntimeError("503 UNAVAILABLE overloaded")])
async def test_a_provider_failure_removes_the_sentence(error: Exception) -> None:
    assert await report_check(_ctx(LLM([error])), _writing(), f"{TIE_WINNER} {FINE}") == (FINE, 1)


@pytest.mark.parametrize("error", [BudgetExceeded("cost", "turn budget"), KeyError("bug")])
async def test_any_other_error_fails_the_turn(error: Exception) -> None:
    with pytest.raises(type(error)):
        await report_check(_ctx(LLM([error])), _writing(), TIE_WINNER)


async def test_the_answer_runs_all_four_rules_and_says_what_it_removed() -> None:
    case = CaseFile(cars=[CaseCar(key="car#1", request_text="Sorento"), CaseCar(key="car#2", request_text="Prado")])
    comp = Computed(blocks=[], facts={}, criteria=None, check=CI)
    llm = LLM([f"{FINE} {TIE_WINNER}", f"{FINE} {TIE_WINNER}"])  # the answer, then its rewrite: still a winner
    inp = AnswerIn(language="ru", user_text="кто лучше?", decision={"kind": "ANSWER_FROM_CONTEXT"})
    text, removed = await write_answer(_ctx(llm), inp, case, comp, nothing_new=False)
    assert removed == 1 and llm.calls == ["answerer", "answerer"]
    assert text == f"{FINE}\n\n{t('guard_removed', 'ru')}"


def test_no_removal_no_notice() -> None:
    assert with_notice(FINE, 0, "es") == FINE
    assert with_notice(FINE, 2, "es").endswith(t("guard_removed", "es"))
