"""The stores' failure contract (chat/application/ports.py): a driver error never leaves a store — it becomes
StoreUnavailable with the cause chained; the ports' own errors pass through unchanged."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from automind.chat.application.ports import StoreUnavailable, TurnBusy
from automind.chat.infrastructure.persistence.errors import store_errors


@store_errors
async def _fails(error: Exception) -> int:
    raise error


@store_errors
async def _works(x: int) -> int:
    return x + 1


async def test_a_driver_error_becomes_store_unavailable_with_its_cause() -> None:
    cause = OperationalError("SELECT 1", {}, ConnectionRefusedError("refused"))
    with pytest.raises(StoreUnavailable, match="_fails: OperationalError") as info:
        await _fails(cause)
    assert info.value.__cause__ is cause


async def test_a_lost_connection_becomes_store_unavailable() -> None:
    with pytest.raises(StoreUnavailable):
        await _fails(ConnectionResetError("reset"))


async def test_the_ports_own_errors_and_results_pass_through() -> None:
    with pytest.raises(TurnBusy):
        await _fails(TurnBusy("a turn is running"))
    assert await _works(1) == 2
