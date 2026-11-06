"""Usage accounting rows: every model call (`llm_calls`) and search (`search_calls`), charged to a turn or a job."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from automind.shared.infrastructure.db.models import (
    LLMCall,
    SearchCall,
)
from automind.shared.infrastructure.db.session import sessionmaker


class UsageRepo:
    async def record_llm(
        self,
        *,
        chat_id: str | None,
        turn_id: str | None,
        role: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        cost_eur: float,
        job_id: str | None = None,
        area: str | None = None,
        primary_model: str | None = None,
        fallback: bool = False,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        prompt_hash: str | None = None,
    ) -> None:
        async with sessionmaker()() as s:
            s.add(
                LLMCall(
                    primary_model=primary_model,
                    fallback=fallback,
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                    prompt_hash=prompt_hash,
                    chat_id=chat_id,
                    turn_id=turn_id,
                    role=role,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cost_eur=cost_eur,
                    job_id=job_id,
                    area=area,
                )
            )
            await s.commit()

    async def record_search(
        self,
        *,
        chat_id: str | None,
        turn_id: str | None,
        kind: str,
        credits: float,
        cost_eur: float,
        job_id: str | None = None,
        area: str | None = None,
        provider: str = "tavily",
        cached: bool = False,
    ) -> None:
        async with sessionmaker()() as s:
            s.add(
                SearchCall(
                    chat_id=chat_id, turn_id=turn_id, kind=kind, credits=credits, cost_eur=cost_eur, job_id=job_id,
                    area=area, provider=provider, cached=cached,
                )
            )  # fmt: skip
            await s.commit()

    async def area_averages(self, min_jobs: int = 3) -> dict[str, tuple[float, float, float]]:
        """Per area: (avg input tokens, avg output tokens, avg searches) per research job (R12).

        Areas with fewer than `min_jobs` recorded jobs are left out (the default applies).
        """
        async with sessionmaker()() as s:
            llm = await s.execute(
                select(
                    LLMCall.area,
                    func.count(func.distinct(LLMCall.job_id)),
                    func.sum(LLMCall.input_tokens),
                    func.sum(LLMCall.output_tokens),
                )
                .where(LLMCall.job_id.is_not(None))
                .group_by(LLMCall.area)
            )
            srch = await s.execute(
                select(
                    SearchCall.area,
                    func.count(func.distinct(SearchCall.job_id)),
                    func.count(SearchCall.id).filter(SearchCall.cached.is_(False)),  # cache hits cost nothing
                )
                .where(SearchCall.job_id.is_not(None))
                .group_by(SearchCall.area)
            )
            searches = {a: (int(j), int(n)) for a, j, n in srch.all()}
        out: dict[str, tuple[float, float, float]] = {}
        for area, jobs, tin, tout in llm.all():
            if area and jobs >= min_jobs:
                sj, sn = searches.get(area, (jobs, 0))
                out[area] = (int(tin or 0) / jobs, int(tout or 0) / jobs, sn / max(sj, 1))
        return out

    async def turn_totals(self, turn_id: str) -> dict[str, Any]:
        """Sum of recorded usage for a turn (used to verify the live counters, SC-012)."""
        async with sessionmaker()() as s:
            llm = (
                await s.execute(
                    select(
                        func.count(LLMCall.id),
                        func.coalesce(func.sum(LLMCall.input_tokens), 0),
                        func.coalesce(func.sum(LLMCall.output_tokens), 0),
                        func.coalesce(func.sum(LLMCall.cost_eur), 0),
                    ).where(LLMCall.turn_id == turn_id)
                )
            ).one()
            srch = (
                await s.execute(
                    select(func.count(SearchCall.id), func.coalesce(func.sum(SearchCall.cost_eur), 0)).where(
                        SearchCall.turn_id == turn_id, SearchCall.cached.is_(False)
                    )
                )
            ).one()
        return {
            "llm_calls": int(llm[0]),
            "input_tokens": int(llm[1]),
            "output_tokens": int(llm[2]),
            "search_calls": int(srch[0]),
            "cost_eur": round(float(llm[3]) + float(srch[1]), 5),
        }
