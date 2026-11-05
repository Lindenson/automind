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

    async def lineup(self, make: str, *, official: str | None, max_pages: int) -> api.LineupRead | None:
        return await api.lineup(make, official=official, max_pages=max_pages, ports=self.ports)

    async def versions(self, make: str, model: str, generation: str | None, *, year: int | None, queries: list[str],
                       limits: dict[str, Any], done: set[str] | None = None) -> api.VersionsRead | None:  # fmt: skip
        return await api.versions(make, model, generation, year=year, queries=queries, limits=limits, done=done,
                                  ports=self.ports)  # fmt: skip

    async def generation_hints(self, query: str, *, lineup_url: str | None = None, user_url: str | None = None,
                               prices: bool = False) -> list[api.WebHint]:  # fmt: skip
        return await api.generation_hints(query, lineup_url=lineup_url, user_url=user_url, prices=prices,
                                          ports=self.ports)  # fmt: skip
