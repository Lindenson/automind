"""LangChain callback that charges every model call to the current TurnBudget and records it.

Attached to every chat model the gateway creates, including models handed to `create_agent`, so
analyst-agent calls are counted too (FR-042, SC-012). It runs before the call (limits) and after
it (tokens, €, `llm_calls` row).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from automind.application.usage import Prices, current_budget, current_job
from automind.infrastructure.db.repositories import UsageRepo


class UsageCallbackHandler(AsyncCallbackHandler):
    raise_error = True  # a BudgetExceeded raised before the call must abort it

    def __init__(self, role: str, model: str, prices: Prices, repo: UsageRepo | None = None) -> None:
        self.role = role
        self.model = model
        self.prices = prices
        self.repo = repo or UsageRepo()
        self._started: dict[UUID, float] = {}

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: UUID, **kwargs: Any
    ) -> None:
        budget = current_budget.get()
        if budget is not None:
            budget.before_llm_call(self.role)
        self._started[run_id] = time.monotonic()

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._started.pop(run_id, time.monotonic())
        in_tok, out_tok = _tokens(response)
        budget = current_budget.get()
        if budget is not None:
            cost = budget.after_llm_call(self.model, in_tok, out_tok)
        else:
            cost = self.prices.llm_cost(self.model, in_tok, out_tok)
        await self.repo.record_llm(
            chat_id=budget.chat_id if budget else None,
            turn_id=budget.turn_id if budget else None,
            role=self.role,
            model=self.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_eur=round(cost, 6),
            job_id=job[0] if (job := current_job.get()) else None,
            area=job[1] if job else None,
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """A failed call was counted before it started; record it too, so shown and stored usage agree."""
        started = self._started.pop(run_id, None)
        if started is None:
            return
        budget = current_budget.get()
        job = current_job.get()
        await self.repo.record_llm(
            chat_id=budget.chat_id if budget else None,
            turn_id=budget.turn_id if budget else None,
            role=self.role,
            model=self.model,
            input_tokens=0,
            output_tokens=0,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_eur=0.0,
            job_id=job[0] if job else None,
            area=job[1] if job else None,
        )


def _tokens(response: LLMResult) -> tuple[int, int]:
    """Input/output tokens from the message usage metadata (fallback: llm_output token_usage)."""
    for gens in response.generations:
        for g in gens:
            msg = getattr(g, "message", None)
            usage = getattr(msg, "usage_metadata", None)
            if usage:
                return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    tu = (response.llm_output or {}).get("token_usage") or {}
    return int(tu.get("prompt_tokens", 0)), int(tu.get("completion_tokens", 0))
