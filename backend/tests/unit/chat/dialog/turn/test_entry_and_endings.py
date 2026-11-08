"""How a message enters a chat (`route`) and how a stopped turn still answers (`ending_for`)."""

import pytest
from langgraph.errors import GraphRecursionError

from automind.chat.dialog.turn.endings import GRAPH_STEPS, TURN_TIMEOUT, ending_for, user_error_text
from automind.chat.dialog.turn.entry import Entry, route
from automind.chat.domain.turn import PresetKind, TurnStatus
from automind.shared.contracts.provider_failure import ProviderUnavailable
from automind.shared.metering.usage import BudgetExceeded

K, S = PresetKind, TurnStatus


@pytest.mark.parametrize(("open_turn", "kind", "entry"), [
    (None, None, Entry.START), (None, K.CAR_EDIT, Entry.START), (None, K.RESCORE, Entry.START),
    (S.RUNNING, None, Entry.BUSY_RUNNING), (S.RUNNING, K.CAR_EDIT, Entry.BUSY_RUNNING),
    (S.WAITING, None, Entry.ANSWER), (S.WAITING, K.RESEARCH_MORE, Entry.ANSWER),
    (S.WAITING, K.CAR_EDIT, Entry.REPLACE_QUESTION),
    (S.WAITING, K.RESCORE, Entry.BUSY_QUESTION_OPEN), (S.WAITING, K.REPORT_SAVED, Entry.BUSY_QUESTION_OPEN),
])  # fmt: skip
def test_route(open_turn: TurnStatus | None, kind: PresetKind | None, entry: Entry) -> None:
    assert route(open_turn, kind) is entry


def test_endings_by_exception_type() -> None:
    limit = ending_for(BudgetExceeded("llm_calls", "20 model calls"))
    assert limit is not None and limit.phrase == "run_limit" and limit.limit is None
    timeout = ending_for(TimeoutError())
    assert timeout is not None and timeout.limit == TURN_TIMEOUT and timeout.report_saved
    loop = ending_for(GraphRecursionError("loop"))
    assert loop is not None and loop.limit == GRAPH_STEPS and loop.phrase == "run_loop"
    down = ending_for(ProviderUnavailable("every model busy"))
    assert down is not None and down.provider_down


def test_a_bug_has_no_ending_and_a_plain_message() -> None:
    assert ending_for(KeyError("x")) is None and ending_for(RuntimeError("boom")) is None
    assert "Something went wrong" in user_error_text(KeyError("503"))  # a bug, even with "503" in its text
