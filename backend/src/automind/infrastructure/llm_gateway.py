"""LLM gateway (constitution VII): the single place that creates chat models.

Provider and model per role come from config/models.yaml ("provider:model"). Every model carries
the usage callback, so all calls, including those made by `create_agent` analysts, are limited
and recorded per turn (FR-041, FR-042).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from functools import lru_cache
from typing import Any, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from automind.acquisition.domain import served as _served
from automind.acquisition.domain.served import ServedCall, served
from automind.application.usage import BudgetExceeded, Limits, Prices, TurnBudget, current_budget
from automind.config import settings
from automind.infrastructure import config as cfg
from automind.infrastructure.usage_callback import UsageCallbackHandler, current_prompt, prompt_identity

log = logging.getLogger(__name__)

__all__ = [
    "BudgetExceeded",
    "ServedCall",
    "TurnBudget",
    "chat_model",
    "current_budget",
    "limits",
    "model_name",
    "models_by_role",
    "new_budget",
    "prices",
    "served",
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
        daily_cap_eur=s.daily_cap_eur,
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


TRANSIENT_PAUSE_S = 120.0


def transient(error: BaseException) -> bool:
    """Provider overloaded or briefly down (503 UNAVAILABLE, 500, 'high demand', 'overloaded')."""
    text = str(error)
    return any(k in text for k in ("503", "UNAVAILABLE", "high demand", "overloaded", "Overloaded", "500 INTERNAL"))


def mark_exhausted(name: str, error: BaseException) -> bool:
    """Skip a model for a while: until its quota resets, or 2 minutes when it is overloaded."""
    wait = quota_exhausted(error)
    if wait is None and transient(error):
        wait = TRANSIENT_PAUSE_S
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
    kwargs["callbacks"] = [UsageCallbackHandler(role, name, prices(), primary=model_name(role))]
    return init_chat_model(name, **kwargs)


def chat_model(role: str) -> BaseChatModel:
    return _build(role, candidates(role)[0])


_LLM_SEM: dict[int, asyncio.Semaphore] = {}  # per event loop (tests run several loops)
LLM_TOTAL = 16  # default; config/search.yaml concurrency.llm_total


def _slots() -> asyncio.Semaphore:
    """One limit on model calls in flight across all jobs, so parallel research does not trip rate limits."""
    loop = id(asyncio.get_running_loop())
    if loop not in _LLM_SEM:
        conc = cfg.search_config().get("concurrency") or {}
        _LLM_SEM[loop] = asyncio.Semaphore(int(conc.get("llm_total", LLM_TOTAL)))
    return _LLM_SEM[loop]


async def _with_fallbacks(role: str, call: Any) -> Any:
    async with _slots():
        return await _try_models(role, call)


async def _try_models(role: str, call: Any) -> Any:
    """Try the role's model, then its fallbacks; an overloaded or used-up model is skipped for a while.
    When every model is overloaded, wait briefly and try the first one once more."""
    last: BaseException | None = None
    for attempt in range(2):
        names = candidates(role) if attempt == 0 else [model_name(role), *cfg.model_fallbacks(model_name(role))][:1]
        for name in names:
            try:
                return await call(_build(role, name))
            except BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - only quota/overload errors move on to the next model
                if not mark_exhausted(name, e):
                    raise
                last = e
        if last is not None and not transient(last):
            break
        await asyncio.sleep(5)
    assert last is not None
    raise ProviderUnavailable(str(last)) from last


class ProviderUnavailable(RuntimeError):
    """Every model of a role is overloaded or out of quota (shown to the user as a plain message)."""


async def structured(role: str, schema: type[T], system: str, user: str) -> T:
    async def call(model: BaseChatModel) -> Any:
        return await model.with_structured_output(schema, include_raw=True).ainvoke(
            [("system", system), ("user", user)]
        )

    _served.begin(role)  # spec 011 T009: `served(role)` names the model and prompt version that answer this call
    token = current_prompt.set(prompt_identity(role, system))
    try:
        out = await _with_fallbacks(role, call)
    finally:
        current_prompt.reset(token)
    if out.get("parsing_error") or out.get("parsed") is None:
        raise ValueError(f"{role}: structured output failed: {out.get('parsing_error')}")
    parsed: T = out["parsed"]
    return parsed


async def text(role: str, system: str, user: str) -> str:
    async def call(model: BaseChatModel) -> Any:
        return await model.ainvoke([("system", system), ("user", user)])

    _served.begin(role)
    token = current_prompt.set(prompt_identity(role, system))
    try:
        msg = await _with_fallbacks(role, call)
    finally:
        current_prompt.reset(token)
    content = msg.text if isinstance(getattr(msg, "text", None), str) else str(msg.content)
    return str(content)
