"""The computations of a turn (constitution IX: inputs, assumptions, versions kept): the ownership-cost estimates
(`tco_estimates`) and the race simulation (`simulations`). Implements `application.ports.ComputationStore`."""

from __future__ import annotations

from typing import Any

from automind.shared.infrastructure import db


class ComputationRepo:
    async def record(self, turn_id: str, estimates: list[dict[str, Any]], simulation: dict[str, Any] | None) -> None:
        async with db.sessionmaker()() as s:
            for e in estimates:
                s.add(db.TcoEstimateRow(turn_id=turn_id, **e))
            if simulation is not None:
                s.add(db.Simulation(turn_id=turn_id, **simulation))
            await s.commit()
