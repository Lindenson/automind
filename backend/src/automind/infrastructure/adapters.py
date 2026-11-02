"""Live implementations of the application ports (composition happens in api/app.py)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

from langchain.agents import create_agent
from pydantic import BaseModel

from automind.application.ports import Ports
from automind.domain.cost import AreaAverage, CostPrices, estimate
from automind.infrastructure import llm_gateway
from automind.infrastructure.config import fetch_policy, reference, search_config
from automind.infrastructure.db.repositories import CaseRepo, JobRepo, MessageRepo, TurnRepo, UsageRepo
from automind.infrastructure.events import EventBus
from automind.infrastructure.fetch import Fetcher, FetchPolicy
from automind.infrastructure.pages import DbPageStore
from automind.infrastructure.search.cache import CachedSearcher
from automind.infrastructure.search.serpapi import SerpApiProvider
from automind.infrastructure.search.serper import SerperProvider
from automind.infrastructure.search.tavily import TavilyProvider
from automind.infrastructure.site_readers import live_readers

T = TypeVar("T", bound=BaseModel)


class LiveLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        return await llm_gateway.structured(role, schema, system, user)

    async def text(self, role: str, system: str, user: str) -> str:
        return await llm_gateway.text(role, system, user)

    def agent(self, role: str, tools: list[Any], system_prompt: str) -> Any:
        # The model carries the usage callback, so every agent step is counted (FR-042).
        return create_agent(llm_gateway.chat_model(role), tools, system_prompt=system_prompt)


def live_search() -> CachedSearcher:
    """Cache-first searcher over the providers named in config/search.yaml (primary, then fallback)."""
    cfg = search_config()
    make = {"serper": SerperProvider, "serpapi": SerpApiProvider, "tavily": TavilyProvider}
    names = [cfg["provider"], *[p for p in cfg.get("fallback") or [] if p != cfg["provider"]]]
    return CachedSearcher([make[n]() for n in names], cfg)


def live_pages() -> DbPageStore:
    return DbPageStore(Fetcher(FetchPolicy.from_config(fetch_policy())))


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def live_ports(events: EventBus, prompts: dict[str, str]) -> Ports:
    return Ports(
        llm=LiveLLM(),
        search=live_search(),
        cases=CaseRepo(),
        turns=TurnRepo(),
        events=events,
        jobs=JobRepo(),
        clock=SystemClock(),
        ref=reference(prompts),
        messages=MessageRepo(),
        estimator=LiveEstimator(),
        pages=live_pages(),
        readers=live_readers(),
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
            eur_per_search=p.query_cost(search_config()["provider"]),
        )
        averages = {a: AreaAverage(*v) for a, v in (await self.repo.area_averages()).items()}
        return estimate(jobs, rounds=rounds, averages=averages, default=self.DEFAULT, prices=prices)
