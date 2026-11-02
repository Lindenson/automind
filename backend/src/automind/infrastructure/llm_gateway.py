"""LLM gateway (constitution VII): the single place that creates chat models.

Provider and model per role come from config/models.yaml ("provider:model"). Every model carries
the usage callback, so all calls, including those made by `create_agent` analysts, are limited
and recorded per turn (FR-041, FR-042).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from automind.application.usage import BudgetExceeded, Limits, Prices, TurnBudget, current_budget
from automind.config import settings
from automind.infrastructure import config as cfg
from automind.infrastructure.usage_callback import UsageCallbackHandler

__all__ = [
    "BudgetExceeded",
    "TurnBudget",
    "chat_model",
    "current_budget",
    "limits",
    "model_name",
    "models_by_role",
    "new_budget",
    "prices",
    "structured",
    "text",
]

T = TypeVar("T", bound=BaseModel)


@lru_cache
def prices() -> Prices:
    return Prices.from_config(cfg.prices())


def limits() -> Limits:
    s = settings()
    return Limits(
        max_llm_calls=s.max_llm_calls_per_turn,
        hard_cap_eur=s.cost_hard_cap_eur,
        confirm_threshold_eur=s.cost_confirm_threshold_eur,
        max_concurrency=s.max_concurrency,
        job_timeout_s=s.job_timeout_s,
        turn_timeout_s=s.turn_timeout_s,
    )


def new_budget(chat_id: str | None, turn_id: str | None) -> TurnBudget:
    return TurnBudget(chat_id=chat_id, turn_id=turn_id, prices=prices(), limits=limits())


def models_by_role() -> dict[str, str]:
    return cfg.models()


def model_name(role: str) -> str:
    roles = cfg.models()
    if role not in roles:
        raise KeyError(f"no model configured for role {role!r} in config/models.yaml")
    return roles[role]


def chat_model(role: str) -> BaseChatModel:
    s = settings()
    name = model_name(role)
    kwargs: dict[str, Any] = {"timeout": s.request_timeout_s * 4, "max_retries": 2}
    if name.startswith("openai:") and s.openai_api_key:
        kwargs["api_key"] = s.openai_api_key
    if name.startswith("anthropic:") and s.anthropic_api_key:
        kwargs["api_key"] = s.anthropic_api_key
    kwargs["callbacks"] = [UsageCallbackHandler(role, name, prices())]
    return init_chat_model(name, **kwargs)


async def structured(role: str, schema: type[T], system: str, user: str) -> T:
    runnable = chat_model(role).with_structured_output(schema, include_raw=True)
    out = await runnable.ainvoke([("system", system), ("user", user)])
    if out.get("parsing_error") or out.get("parsed") is None:
        raise ValueError(f"{role}: structured output failed: {out.get('parsing_error')}")
    parsed: T = out["parsed"]
    return parsed


async def text(role: str, system: str, user: str) -> str:
    msg = await chat_model(role).ainvoke([("system", system), ("user", user)])
    content = msg.text if isinstance(getattr(msg, "text", None), str) else str(msg.content)
    return str(content)
