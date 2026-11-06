"""Live engine ports (spec 011 contracts/acquire.md "Ports"): the cache-first searcher, the page store under the fetch
policy, the site readers, the source registry, model access through the gateway, metrics and the
market-facts store. `live_acq_ports()` builds them once per process; the API process passes its own shared parts
(model access, reference data, registry) so the chat and the engine use the same ones."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from automind.acquisition.gold.versions import live_rows
from automind.acquisition.infrastructure.config import fetch_policy
from automind.acquisition.infrastructure.fetch import Fetcher, FetchPolicy
from automind.acquisition.infrastructure.pages import DbPageStore
from automind.acquisition.infrastructure.search.cache import CachedSearcher
from automind.acquisition.infrastructure.search.serpapi import SerpApiProvider
from automind.acquisition.infrastructure.search.serper import SerperProvider
from automind.acquisition.infrastructure.search.tavily import TavilyProvider
from automind.acquisition.parsing.registry import live_readers
from automind.acquisition.ports import AcqPorts
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.infrastructure.repo import RegistryRepo
from automind.chat.infrastructure.persistence.repositories import MarketFactRepo
from automind.observability.metrics import prom
from automind.shared.contracts.config import Reference
from automind.shared.infrastructure.config.loader import reference, search_config

# the prompts are versioned files next to the chat's (orchestration/prompts/*.md); read as files, never imported
PROMPTS = Path(__file__).resolve().parents[2] / "chat" / "dialog" / "prompts"


def live_search() -> CachedSearcher:
    """Cache-first searcher over the providers named in config/search.yaml (primary, then fallback)."""
    cfg = search_config()
    make = {"serper": SerperProvider, "serpapi": SerpApiProvider, "tavily": TavilyProvider}
    names = [cfg["provider"], *[p for p in cfg.get("fallback") or [] if p != cfg["provider"]]]
    return CachedSearcher([make[n]() for n in names], cfg)


def live_pages() -> DbPageStore:
    return DbPageStore(Fetcher(FetchPolicy.from_config(fetch_policy())))


def engine_ports(llm: Any, ref: Reference, registry: Any = None) -> AcqPorts:
    """The engine's live ports around shared model access, reference data and registry."""
    return AcqPorts(
        llm=llm,
        ref=ref,
        search=live_search(),
        pages=live_pages(),
        readers=live_readers(),
        registry=registry if registry is not None else RegistryService(RegistryRepo(ref.registry), ref.registry),
        metrics=prom.inc,
        market_facts=MarketFactRepo(),
        datasets=live_rows,
    )


@cache
def live_acq_ports() -> AcqPorts:
    """This process's engine ports (the worker, `acquisition.api` calls without ports)."""
    from automind.chat.infrastructure.adapters import LiveLLM  # noqa: PLC0415 - the gateway-backed model port

    prompts = {p.stem: p.read_text(encoding="utf-8").strip() for p in sorted(PROMPTS.glob("*.md"))}
    return engine_ports(LiveLLM(), reference(prompts))
