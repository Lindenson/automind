"""Model access per role: the protocol both the chat and the engine call (the gateway implements it)."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    """Model access per role. Usage is charged to the current TurnBudget by the implementation."""

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...

    async def text(self, role: str, system: str, user: str) -> str: ...

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> Any:
        """A `create_agent`-compatible runnable for analyst roles (scoped MCP tools)."""
        ...
