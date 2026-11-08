"""The turn lifecycle table (chat/domain/turn.py): the steps the runner takes are allowed, the others refused."""

import pytest

from automind.chat.domain.turn import (
    FINAL,
    IllegalTransition,
    PresetKind,
    TurnStatus,
    check_move,
    preset_kind,
)

S = TurnStatus


@pytest.mark.parametrize(("current", "to"), [
    (S.RUNNING, S.RUNNING),  # a restart continues the turn
    (S.RUNNING, S.WAITING), (S.RUNNING, S.DONE), (S.RUNNING, S.FAILED), (S.RUNNING, S.CANCELLED),
    (S.WAITING, S.RUNNING), (S.WAITING, S.CANCELLED),
])  # fmt: skip
def test_allowed_steps(current: TurnStatus, to: TurnStatus) -> None:
    check_move(current, to)


@pytest.mark.parametrize("final", sorted(FINAL))
@pytest.mark.parametrize("to", list(TurnStatus))
def test_a_final_status_is_final(final: TurnStatus, to: TurnStatus) -> None:
    with pytest.raises(IllegalTransition):
        check_move(final, to)


@pytest.mark.parametrize("to", [S.DONE, S.FAILED, S.WAITING])
def test_a_waiting_turn_only_resumes_or_is_cancelled(to: TurnStatus) -> None:
    with pytest.raises(IllegalTransition):
        check_move(S.WAITING, to)


def test_statuses_equal_the_stored_strings() -> None:
    assert S.WAITING == "WAITING_CONFIRMATION" and S("DONE") is S.DONE


def test_preset_kind_of_the_graph_states_plain_dict() -> None:
    assert preset_kind({"kind": "car_edit", "car_key": "A"}) is PresetKind.CAR_EDIT
    assert preset_kind(None) is None and preset_kind({"kind": "unknown"}) is None and preset_kind({}) is None
