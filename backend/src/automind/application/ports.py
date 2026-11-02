"""Application ports: the interfaces the application layer depends on (constitution V, IX).

Infrastructure provides real implementations; tests provide fakes (tests/fakes). Application code
receives a `Ports` bundle instead of importing infrastructure, so graph workflows can run with a
scripted LLM and fixture search.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from automind.domain.identity import Aliases

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Reference:
    """Static reference data from config/*.yaml, loaded by infrastructure and passed in."""

    aliases: Aliases
    generations: dict[str, list[tuple[str, int | None, int | None]]]
    questions: dict[str, str]
    prompts: dict[str, str]
    queries: dict[str, list[str]]
    criteria: Any = None  # domain.criteria.CriteriaModel (config/criteria.yaml)
    rates: dict[str, Any] | None = None  # config/rates.yaml (TCO)


@dataclass
class WebDoc:
    url: str
    title: str
    text: str
    snippet_only: bool


class LLM(Protocol):
    """Model access per role. Usage is charged to the current TurnBudget by the implementation."""

    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...

    async def text(self, role: str, system: str, user: str) -> str: ...

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> Any:
        """A `create_agent`-compatible runnable for analyst roles (scoped MCP tools)."""
        ...


class Search(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[WebDoc]: ...

    async def extract(self, url: str) -> WebDoc | None: ...

    async def fill_full_text(self, docs: list[WebDoc]) -> None: ...


class CaseRepo(Protocol):
    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]: ...

    async def save_version(self, chat_id: str, data: dict[str, Any], changed_by: str, change_log: list[str]) -> int: ...


class TurnRepo(Protocol):
    async def start(self, chat_id: str, user_message_id: str | None, case_version: int) -> Any: ...

    async def update(self, turn_id: str, **values: Any) -> None: ...

    async def get(self, turn_id: str) -> Any | None: ...

    async def active(self, chat_id: str) -> Any | None: ...

    async def last_report_fingerprint(self, chat_id: str) -> str | None: ...

    async def running(self) -> list[Any]: ...


class EventBus(Protocol):
    async def publish(self, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int: ...


class CatalogRepo(Protocol):
    async def find(self, make: str, model: str, generation: str | None, year: int | None) -> list[Any]: ...


class EvidenceRepo(Protocol):
    async def selected_values(self, variant_id: str) -> dict[str, Any]: ...


class JobRepo(Protocol):
    async def create(self, chat_id: str, turn_id: str, variant_id: str, area: str, round_: int) -> Any: ...

    async def mark(self, job_id: str, status: str, **values: Any) -> None: ...

    async def for_turn(self, turn_id: str) -> list[Any]: ...

    async def get(self, job_id: str) -> Any | None: ...

    async def skip_open(self, turn_id: str, reason: str = "cancelled") -> int: ...


class MessageRepo(Protocol):
    async def history(self, chat_id: str) -> list[Any]: ...


class Estimator(Protocol):
    """Research cost estimate (FR-041): jobs are (variant_id, area)."""

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]
"""Progress/event callback: (type, payload)."""


@dataclass
class Ports:
    llm: LLM
    search: Search
    cases: CaseRepo
    turns: TurnRepo
    events: EventBus
    jobs: JobRepo
    clock: Clock
    ref: Reference
    messages: MessageRepo
    estimator: Estimator
