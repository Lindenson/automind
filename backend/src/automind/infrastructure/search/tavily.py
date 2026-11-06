"""Tavily, reduced to search hits (spec 003: fallback / baseline only; page text comes from our page store)."""

from __future__ import annotations

from tavily import AsyncTavilyClient

from automind.config import settings
from automind.shared.contracts.web import SearchHit

from . import SearchUnavailable


class TavilyProvider:
    name = "tavily"

    async def search(self, query: str, *, gl: str, hl: str, num: int = 10) -> list[SearchHit]:
        key = settings().tavily_api_key
        if not key:
            raise SearchUnavailable("TAVILY_API_KEY is not set (add it to .env)")
        try:
            res = await AsyncTavilyClient(api_key=key).search(
                query=query, max_results=min(num, 10), search_depth="advanced", timeout=settings().request_timeout_s
            )
        except Exception as e:  # noqa: BLE001 - any client error means the provider is unavailable
            raise SearchUnavailable(f"tavily: {type(e).__name__}") from e
        return [
            SearchHit(
                url=str(r["url"]),
                title=str(r.get("title") or ""),
                snippet=str(r.get("content") or "")[:500],
                rank=i + 1,
            )  # fmt: skip
            for i, r in enumerate(res.get("results") or [])
            if r.get("url")
        ]
