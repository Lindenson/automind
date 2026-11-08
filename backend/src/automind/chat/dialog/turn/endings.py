"""How a turn that stopped early still answers: one table from the exception to the plain reply (never a bare
FAILED for a limit, a loop or a provider that is down).

    exception                   reply phrase                         limit noted     else
    ─────────                   ────────────                         ───────────     ────
    BudgetExceeded              run_limit (what = the limit)         (by the budget)
    TimeoutError (turn time)    run_timeout | run_timeout_saved      turn_timeout    report from saved data
    GraphRecursionError         run_loop                             graph_steps
    transient provider failure  run_provider_down                                    provider_down signal
    anything else               — (the turn FAILS and the error is re-raised)
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.errors import GraphRecursionError

from automind.chat.dialog.retry import transient_provider_error
from automind.shared.contracts.provider_failure import BUSY, classify
from automind.shared.metering.usage import BudgetExceeded

TURN_TIMEOUT = "turn_timeout"
GRAPH_STEPS = "graph_steps"


@dataclass(frozen=True)
class Ending:
    """The reply of a turn that stopped early (`phrases` keys) and what it leaves behind."""

    phrase: str
    what: str | None = None  # the `what` of the phrase (the limit's message)
    limit: str | None = None  # added to the budget's limits_reached
    phrase_when_saved: str | None = None  # the phrase when research results were saved before the stop
    report_saved: bool = False  # then a follow-up turn writes the report from them
    provider_down: bool = False


def ending_for(error: Exception) -> Ending | None:
    """The ending of a turn stopped by `error`; None when the turn has failed."""
    match error:
        case BudgetExceeded():
            return Ending("run_limit", what=str(error))
        case TimeoutError():
            return Ending("run_timeout", limit=TURN_TIMEOUT, phrase_when_saved="run_timeout_saved", report_saved=True)
        case GraphRecursionError():
            return Ending("run_loop", limit=GRAPH_STEPS)
        case _ if transient_provider_error(error):
            return Ending("run_provider_down", provider_down=True)
    return None


_BUSY_TEXT = ("The AI service is overloaded or out of quota right now. Nothing is lost: send the message again in a "
              "minute. / Сервис ИИ сейчас перегружен или исчерпал квоту. Ничего не потеряно — отправьте сообщение ещё "
              "раз через минуту.")  # fmt: skip
_FAILED_TEXT = "Something went wrong on my side. Please try again. / Что-то пошло не так. Попробуйте ещё раз."


def user_error_text(error: BaseException) -> str:
    """The plain message of a FAILED turn; technical details stay in the event's `detail` and in the logs."""
    return _BUSY_TEXT if classify(error) in BUSY else _FAILED_TEXT
