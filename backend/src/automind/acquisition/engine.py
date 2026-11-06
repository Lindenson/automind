"""The engine bound to its ports: what the chat's `Ports.acquisition` holds (`application/ports.py:
AcquisitionPort`), so graph tests can fake the engine and live code wires it once (strangler S8)."""

from __future__ import annotations

from typing import Any

from automind.acquisition import api
from automind.acquisition.ports import AcqPorts


class Engine:
    def __init__(self, ports: AcqPorts) -> None:
        self.ports = ports

    async def acquire(self, req: api.AcquireRequest, emit: api.Emit | None = None) -> api.AcquireResult:
        return await api.acquire(req, emit, ports=self.ports)

    async def lineup(self, make: str, *, official: str | None, max_pages: int,
                     market: str = "ES") -> api.LineupRead | None:  # fmt: skip
        return await api.lineup(make, official=official, max_pages=max_pages, market=market, ports=self.ports)

    async def versions(self, make: str, model: str, generation: str | None, *, year: int | None, queries: list[str],
                       limits: dict[str, Any], done: set[str] | None = None,
                       market: str = "ES") -> api.VersionsRead | None:  # fmt: skip
        return await api.versions(make, model, generation, year=year, queries=queries, limits=limits, done=done,
                                  market=market, ports=self.ports)  # fmt: skip

    async def generation_hints(self, query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                               prices: bool = False, market: str = "ES") -> list[api.WebHint]:  # fmt: skip
        return await api.generation_hints(query, lineup_url=lineup_url, user_url=user_url, prices=prices,
                                          market=market, ports=self.ports)  # fmt: skip

    async def dataset_versions(self, make: str, model: str, generation: str | None = None, fuel: str | None = None,
                               year_from: int | None = None) -> list[api.DatasetVersion]:  # fmt: skip
        return await api.dataset_versions(make, model, generation, fuel, year_from, ports=self.ports)
