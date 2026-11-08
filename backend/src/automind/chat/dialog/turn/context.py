"""What every graph node receives through LangGraph's runtime context: the ports, the turn and its budget.

Built by the turn execution for each run of the graph; nodes import it from here (never from the runner). Events a
node publishes (`status`, `progress`, any `emit`) go to the chat's event bus under this turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from automind.chat.application.ports import Ports
from automind.chat.application.services.research.contracts import GridCell
from automind.shared.metering.usage import TurnBudget


@dataclass
class TurnContext:
    """The ports, the chat and turn ids and the budget all usage of this run is charged to."""

    ports: Ports
    chat_id: str
    turn_id: str
    budget: TurnBudget

    async def emit(self, type_: str, payload: dict[str, Any]) -> int:
        """Publish an event of this turn; returns its sequence number in the chat."""
        return await self.ports.events.publish(self.chat_id, self.turn_id, type_, payload)

    async def status(self, stage: str, text: str, **extra: Any) -> None:
        """A progress line for the user ("understanding", "researching", …)."""
        await self.emit("status", {"stage": stage, "text": text, **extra})

    async def progress(self, cell: GridCell) -> None:
        """A cell of the research grid (the research service's `ResearchEvents`)."""
        await self.emit("progress", dict(cell))
