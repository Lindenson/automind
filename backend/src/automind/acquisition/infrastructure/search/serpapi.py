"""SerpApi (serpapi.com, a different company from Serper): Google results via GET /search.json."""

from __future__ import annotations

from typing import Any

import httpx

from automind.acquisition.infrastructure.search import SearchUnavailable
from automind.shared.contracts.web import SearchHit
from automind.shared.infrastructure.config.settings import settings

URL = "https://serpapi.com/search.json"


def parse(data: dict[str, Any]) -> list[SearchHit]:
    return [
        SearchHit(
            url=str(r["link"]),
            title=str(r.get("title") or ""),
            snippet=str(r.get("snippet") or ""),
            rank=int(r.get("position") or i + 1),
        )  # fmt: skip
        for i, r in enumerate(data.get("organic_results") or [])
        if r.get("link")
    ]


class SerpApiProvider:
    name = "serpapi"

    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings().serpapi_api_key
        self.transport = transport

    async def search(self, query: str, *, gl: str, hl: str, num: int = 10) -> list[SearchHit]:
        if not self.api_key:
            raise SearchUnavailable("SERPAPI_API_KEY is not set (add it to .env)")
        params = {"engine": "google", "q": query, "gl": gl, "hl": hl, "num": num, "api_key": self.api_key}
        async with httpx.AsyncClient(timeout=settings().request_timeout_s, transport=self.transport) as c:
            try:
                r = await c.get(URL, params=params)
            except httpx.HTTPError as e:
                raise SearchUnavailable(f"serpapi: {type(e).__name__}") from e
        if r.status_code in (401, 402, 403, 429) or r.status_code >= 500:
            raise SearchUnavailable(f"serpapi: HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()
        if data.get("error") and not data.get("organic_results"):
            if "hasn't returned any results" in str(data["error"]):
                return []
            raise SearchUnavailable(f"serpapi: {data['error']}")
        return parse(data)
