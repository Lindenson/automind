"""Live implementations of the application ports (composition happens in api/app.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

from langchain.agents import create_agent
from pydantic import BaseModel

from automind.application.ports import Ports, WebDoc
from automind.domain.cost import AreaAverage, CostPrices, estimate
from automind.infrastructure import llm_gateway, search_tavily
from automind.infrastructure.config import fetch_policy, reference
from automind.infrastructure.db.repositories import CaseRepo, JobRepo, MessageRepo, TurnRepo, UsageRepo
from automind.infrastructure.events import EventBus
from automind.infrastructure.fetch import Fetcher, FetchPolicy, FetchRefused

T = TypeVar("T", bound=BaseModel)


class LiveLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        return await llm_gateway.structured(role, schema, system, user)

    async def text(self, role: str, system: str, user: str) -> str:
        return await llm_gateway.text(role, system, user)

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> Any:
        # The model carries the usage callback, so every agent step is counted (FR-042).
        return create_agent(llm_gateway.chat_model(role), tools, system_prompt=system_prompt)


class LiveSearch:
    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self.fetcher = fetcher or Fetcher(FetchPolicy.from_config(fetch_policy()))

    async def search(self, query: str, max_results: int = 5) -> list[WebDoc]:
        return await search_tavily.search(query, max_results=max_results)

    async def extract(self, url: str) -> WebDoc | None:
        """A pasted URL: direct fetch under the fetch policy; Tavily extract only if fetching failed."""
        try:
            return await self.fetcher.fetch(url)
        except FetchRefused as e:
            if "deny-list" in e.reason or "robots" in e.reason:
                return None  # never work around a refusal
        except Exception:  # noqa: BLE001 - network error: fall back to the search provider
            pass
        return await search_tavily.extract(url)

    async def fill_full_text(self, docs: list[WebDoc]) -> None:
        await search_tavily.fill_full_text(docs)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def live_ports(events: EventBus, prompts: dict[str, str]) -> Ports:
    return Ports(
        llm=LiveLLM(),
        search=LiveSearch(),
        cases=CaseRepo(),
        turns=TurnRepo(),
        events=events,
        jobs=JobRepo(),
        clock=SystemClock(),
        ref=reference(prompts),
        messages=MessageRepo(),
        estimator=LiveEstimator(),
    )


class LiveEstimator:
    """Research cost estimate from learned per-area averages and configured prices (R12, T045)."""

    DEFAULT = AreaAverage(llm_in=14_000, llm_out=1_200, searches=3.5)

    def __init__(self, repo: UsageRepo | None = None) -> None:
        self.repo = repo or UsageRepo()

    async def estimate(self, jobs: list[tuple[str, str]], rounds: int) -> float:
        p = llm_gateway.prices()
        p_in, p_out = p.llm.get(llm_gateway.model_name("extractor"), p.default_llm)
        prices = CostPrices(
            eur_per_m_in=p_in,
            eur_per_m_out=p_out,
            eur_per_search=p.search_cost(p.credits.get("search_advanced", 2)),
        )
        averages = {a: AreaAverage(*v) for a, v in (await self.repo.area_averages()).items()}
        return estimate(jobs, rounds=rounds, averages=averages, default=self.DEFAULT, prices=prices)
