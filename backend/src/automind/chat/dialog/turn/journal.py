"""The turn's status writes, all through the lifecycle table (`chat.domain.turn.check_move`).

`LiveTurn` is the runner's view of one turn: its ids and the status it is in now. `TurnJournal.move` checks the step,
writes it with the given changes and keeps `LiveTurn.status` in step with the row. Closing a turn without an answer
(cancel, or a car edit replacing its question) also skips its open research jobs; data already validated stays
cached (FR-043). Errors: `StoreUnavailable` from the stores propagates; `IllegalTransition` is a bug in the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Unpack

from automind.chat.application.ports import JobRepo, TurnFacts, TurnRepo
from automind.chat.domain.turn import TurnStatus, check_move


@dataclass
class LiveTurn:
    """A turn the runner works on: its chat, its id and its status now."""

    chat_id: str
    turn_id: str
    status: TurnStatus


class TurnJournal:
    """Status writes of turns (the `turns` row) and the research jobs a closed turn leaves open."""

    def __init__(self, turns: TurnRepo, jobs: JobRepo) -> None:
        self.turns = turns
        self.jobs = jobs

    async def move(self, turn: LiveTurn, to: TurnStatus, **facts: Unpack[TurnFacts]) -> None:
        """Step `turn` to `to` (refused when the lifecycle has no such step) and store it with `facts`."""
        check_move(turn.status, to)
        await self.turns.update(turn.turn_id, status=to, **facts)
        turn.status = to

    async def close_unanswered(self, turn: LiveTurn) -> None:
        """Cancel a turn: its open research jobs are skipped, then it is CANCELLED."""
        await self.jobs.skip_open(turn.turn_id)
        await self.move(turn, TurnStatus.CANCELLED)
