"""Web search adapter (Tavily). Search and page extraction are code paths, never LLM tools
(constitution VIII). Deny-listed sites are filtered out."""

from __future__ import annotations

import math

from tavily import AsyncTavilyClient

from automind.application.ports import WebDoc
from automind.application.usage import current_budget, current_job
from automind.config import settings
from automind.domain.evidence import is_denied
from automind.infrastructure.db.repositories import UsageRepo
from automind.infrastructure.llm_gateway import prices

__all__ = ["SearchUnavailable", "WebDoc", "extract", "fill_full_text", "search"]


class SearchUnavailable(RuntimeError):
    pass


def _client() -> AsyncTavilyClient:
    key = settings().tavily_api_key
    if not key:
        raise SearchUnavailable("TAVILY_API_KEY is not set (add it to .env)")
    return AsyncTavilyClient(api_key=key)


def _credits(kind: str, urls: int = 0) -> float:

    c = prices().credits
    if kind == "search_advanced":
        return c.get("search_advanced", 2)
    per5 = c.get(f"{kind}_per_5_urls", 1)
    return per5 * max(1, math.ceil(urls / 5))


async def _charge(kind: str, credits: float) -> None:
    """Check the turn's cost cap before the call (raises BudgetExceeded)."""
    b = current_budget.get()
    if b is not None:
        b.before_search(credits)


async def _record(kind: str, credits: float) -> None:
    """Count the call in the turn budget and persist a `search_calls` row (FR-042)."""

    b = current_budget.get()
    cost = b.after_search(credits) if b is not None else prices().search_cost(credits)
    await UsageRepo().record_search(
        chat_id=b.chat_id if b else None,
        turn_id=b.turn_id if b else None,
        kind="search" if kind.startswith("search") else "extract",
        credits=credits,
        cost_eur=round(cost, 6),
        job_id=job[0] if (job := current_job.get()) else None,
        area=job[1] if job else None,
    )


async def search(query: str, max_results: int = 5, raw: bool = True) -> list[WebDoc]:
    s = settings()
    credits = _credits("search_advanced")
    await _charge("search_advanced", credits)
    res = await _client().search(
        query,
        search_depth="advanced",
        max_results=max_results,
        include_raw_content="text" if raw else False,
        timeout=s.request_timeout_s,
    )
    await _record("search_advanced", credits)
    docs: list[WebDoc] = []
    for r in res.get("results", []):
        url = r.get("url", "")
        if not url or is_denied(url):
            continue
        body = r.get("raw_content") or ""
        snippet_only = not body
        text = (body or r.get("content") or "")[: s.max_doc_chars]
        if text.strip():
            docs.append(WebDoc(url=url, title=r.get("title") or url, text=text, snippet_only=snippet_only))
    return docs


async def fill_full_text(docs: list[WebDoc]) -> None:
    """Replace snippet-only docs with full page text (Tavily extract, advanced), in place."""
    need = [d for d in docs if d.snippet_only]
    if not need:
        return
    s = settings()
    urls = [d.url for d in need][:20]
    credits = _credits("extract_advanced", len(urls))
    await _charge("extract_advanced", credits)
    try:
        res = await _client().extract(
            urls=urls, extract_depth="advanced", format="text", timeout=s.request_timeout_s * 2
        )
    except Exception:
        return
    await _record("extract_advanced", credits)
    by_url = {r.get("url"): (r.get("raw_content") or "") for r in res.get("results", [])}
    for d in need:
        body = by_url.get(d.url, "")
        if len(body) > len(d.text):
            d.text, d.snippet_only = body[: s.max_doc_chars], False


async def extract(url: str) -> WebDoc | None:
    if is_denied(url):
        return None
    credits = _credits("extract_basic", 1)
    await _charge("extract_basic", credits)
    res = await _client().extract(urls=[url], format="text", timeout=settings().request_timeout_s)
    await _record("extract_basic", credits)
    for r in res.get("results", []):
        text = (r.get("raw_content") or "")[: settings().max_doc_chars]
        if text.strip():
            return WebDoc(url=r.get("url", url), title=url, text=text, snippet_only=False)
    return None
