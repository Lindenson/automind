"""LLM gateway (constitution VII): the single place that creates chat models.

Provider and model per role come from config/models.yaml ("provider:model"). Every model carries
the usage callback, so all calls, including those made by `create_agent` analysts, are limited
and recorded per turn (FR-041, FR-042).
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from typing import Any, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from automind.application.usage import BudgetExceeded, Limits, Prices, TurnBudget, current_budget
from automind.config import settings
from automind.infrastructure import config as cfg
from automind.infrastructure.usage_callback import UsageCallbackHandler

log = logging.getLogger(__name__)

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


# Models whose provider quota is used up (e.g. a free tier's requests per day): name -> monotonic time it
# may be tried again. Calls go to the role's fallback models meanwhile (config/models.yaml `fallbacks`).
_EXHAUSTED: dict[str, float] = {}
_RETRY_RE = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.I)


def quota_exhausted(error: BaseException) -> float | None:
    """Seconds until a daily/plan quota resets when the error is one (None for other errors)."""
    text = str(error)
    if "RESOURCE_EXHAUSTED" not in text and "insufficient_quota" not in text:
        return None
    if "PerMinute" in text or "per minute" in text.lower():
        return None  # a short burst limit: the client's own retries handle it
    m = _RETRY_RE.search(text)
    if m and any(m.groups()):
        h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + sec
    return 3600.0


def mark_exhausted(name: str, error: BaseException) -> bool:
    wait = quota_exhausted(error)
    if wait is None:
        return False
    _EXHAUSTED[name] = time.monotonic() + wait
    log.warning("model %s: quota used up, using fallbacks for %.0f min", name, wait / 60)
    return True


def candidates(role: str) -> list[str]:
    """The role's model, then its fallbacks, skipping models whose quota is used up."""
    primary = model_name(role)
    chain = [primary, *cfg.model_fallbacks(primary)]
    now = time.monotonic()
    usable = [n for n in chain if _EXHAUSTED.get(n, 0) <= now]
    return usable or [primary]


def _build(role: str, name: str) -> BaseChatModel:
    s = settings()
    kwargs: dict[str, Any] = {"timeout": s.request_timeout_s * 4, "max_retries": 2}
    if name.startswith("openai:") and s.openai_api_key:
        kwargs["api_key"] = s.openai_api_key
    if name.startswith("anthropic:") and s.anthropic_api_key:
        kwargs["api_key"] = s.anthropic_api_key
    if name.startswith("google_genai:") and s.google_api_key:
        kwargs["google_api_key"] = s.google_api_key
    kwargs.update(cfg.model_options(name))
    kwargs["callbacks"] = [UsageCallbackHandler(role, name, prices())]
    return init_chat_model(name, **kwargs)


def chat_model(role: str) -> BaseChatModel:
    return _build(role, candidates(role)[0])


async def _with_fallbacks(role: str, call: Any) -> Any:
    last: BaseException | None = None
    for name in candidates(role):
        try:
            return await call(_build(role, name))
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - only a used-up quota moves on to the next model
            if not mark_exhausted(name, e):
                raise
            last = e
    assert last is not None
    raise last


async def structured(role: str, schema: type[T], system: str, user: str) -> T:
    async def call(model: BaseChatModel) -> Any:
        return await model.with_structured_output(schema, include_raw=True).ainvoke(
            [("system", system), ("user", user)]
        )

    out = await _with_fallbacks(role, call)
    if out.get("parsing_error") or out.get("parsed") is None:
        raise ValueError(f"{role}: structured output failed: {out.get('parsing_error')}")
    parsed: T = out["parsed"]
    return parsed


async def text(role: str, system: str, user: str) -> str:
    async def call(model: BaseChatModel) -> Any:
        return await model.ainvoke([("system", system), ("user", user)])

    msg = await _with_fallbacks(role, call)
    content = msg.text if isinstance(getattr(msg, "text", None), str) else str(msg.content)
    return str(content)
