"""Cache-first Searcher (spec 003 FR-001, FR-005, FR-006; research R1, R3).

search_cache (Postgres) → primary provider → fallback providers. Deny-listed URLs are dropped before
anything is stored. Every call is recorded in the turn's usage: paid calls with the provider's price,
cache hits with cost 0 and `cached=true` (SC-006).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from automind.application.ports import SearchHit, SearchProvider
from automind.application.usage import current_budget, current_job
from automind.domain.evidence import is_denied
from automind.infrastructure.db import SearchCache, sessionmaker
from automind.infrastructure.db.repositories import UsageRepo
from automind.infrastructure.llm_gateway import prices

from . import SearchUnavailable


def normalise_query(query: str) -> str:
    """Lowercase, collapse spaces, and sort the `site:` group so equivalent queries share a cache entry."""
    tokens = query.lower().split()
    sites = sorted({t[5:] for t in tokens if t.startswith("site:")})
    rest = [t for t in tokens if not t.startswith("site:") and not (sites and t == "or")]
    return " ".join([*rest, " OR ".join(f"site:{x}" for x in sites)] if sites else rest)


def cache_key(query: str, gl: str, hl: str, num: int) -> str:
    return hashlib.sha256(f"{normalise_query(query)}|{gl}|{hl}|{num}".encode()).hexdigest()


def _hits(rows: list[dict[str, Any]]) -> list[SearchHit]:
    return [SearchHit(url=r["url"], title=r.get("title", ""), snippet=r.get("snippet", ""), rank=int(r.get("rank", 0)))
            for r in rows]  # fmt: skip


class CachedSearcher:
    def __init__(self, providers: Sequence[SearchProvider], config: dict[str, Any]) -> None:
        if not providers:
            raise ValueError("at least one search provider is required")
        self.providers = list(providers)
        self.config = config
        self.usage = UsageRepo()

    def _locale(self, market: str) -> tuple[str, str]:
        m = (self.config.get("markets") or {}).get(market) or (self.config.get("markets") or {}).get("ES") or {}
        return str(m.get("gl", "es")), str(m.get("hl", "es"))

    def _ttl(self, area: str | None) -> timedelta:
        days = self.config.get("cache_ttl_days") or {}
        return timedelta(days=float(days.get(area or "", days.get("default", 7))))

    async def _record(self, provider: str, cost: float, cached: bool, area: str | None) -> None:
        b = current_budget.get()
        job = current_job.get()
        await self.usage.record_search(
            chat_id=b.chat_id if b else None, turn_id=b.turn_id if b else None, kind="search",
            credits=0 if cached else 1, cost_eur=round(cost, 6), job_id=job[0] if job else None,
            area=area or (job[1] if job else None), provider=provider, cached=cached,
        )  # fmt: skip

    async def search(self, query: str, *, market: str = "ES", area: str | None = None) -> list[SearchHit]:
        gl, hl = self._locale(market)
        num = int(self.config.get("num", 10))
        key = cache_key(query, gl, hl, num)
        now = datetime.now(UTC)
        async with sessionmaker()() as s:
            row = await s.get(SearchCache, key)
            if row is not None and row.expires_at > now:
                await self._record(row.provider, 0.0, True, area)
                return [h for h in _hits(row.hits) if not is_denied(h.url)]
        errors = []
        for p in self.providers:
            price = prices().query_cost(p.name)
            b = current_budget.get()
            if b is not None:
                b.before_search_eur(price)  # raises BudgetExceeded at the cost cap
            try:
                hits = await p.search(query, gl=gl, hl=hl, num=num)
            except SearchUnavailable as e:
                errors.append(str(e))
                continue
            if b is not None:
                b.after_search_eur(price)
            await self._record(p.name, price, False, area)
            hits = [h for h in hits if not is_denied(h.url)]
            async with sessionmaker()() as s:
                values = {
                    "key": key, "provider": p.name, "query": query, "gl": gl, "hl": hl,
                    "hits": [h.__dict__ for h in hits], "fetched_at": now, "expires_at": now + self._ttl(area),
                }  # fmt: skip
                stmt = insert(SearchCache).values(**values)
                await s.execute(stmt.on_conflict_do_update(index_elements=["key"], set_=values))
                await s.commit()
            return hits
        raise SearchUnavailable("; ".join(errors) or "no search provider available")
