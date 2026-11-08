"""Serper (serper.dev): Google results. POST /search with q, gl, hl, num; 1 credit per query (num ≤ 10)."""

from __future__ import annotations

from typing import Any

import httpx

from automind.acquisition.infrastructure.search import SearchUnavailable
from automind.shared.contracts.web import SearchHit
from automind.shared.infrastructure.config.settings import settings

URL = "https://google.serper.dev/search"


def parse(data: dict[str, Any]) -> list[SearchHit]:
    return [
        SearchHit(
            url=str(r["link"]),
            title=str(r.get("title") or ""),
            snippet=str(r.get("snippet") or ""),
            rank=int(r.get("position") or i + 1),
        )  # fmt: skip
        for i, r in enumerate(data.get("organic") or [])
        if r.get("link")
    ]


class SerperProvider:
    name = "serper"

    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings().serper_api_key
        self.transport = transport

    async def search(self, query: str, *, gl: str, hl: str, num: int = 10) -> list[SearchHit]:
        if not self.api_key:
            raise SearchUnavailable("SERPER_API_KEY is not set (add it to .env)")
        async with httpx.AsyncClient(timeout=settings().request_timeout_s, transport=self.transport) as c:
            try:
                r = await c.post(URL, headers={"X-API-KEY": self.api_key},
                                 json={"q": query, "gl": gl, "hl": hl, "num": num})  # fmt: skip
            except httpx.HTTPError as e:
                raise SearchUnavailable(f"serper: {type(e).__name__}") from e
        if not r.is_success:  # 400 "not enough credits", 401/403 key, 429 rate, 5xx: the provider cannot answer
            raise SearchUnavailable(f"serper: HTTP {r.status_code}")
        return parse(r.json())
