"""Transient provider errors (spec 007 FR-028): what an LLM node retries, and what the user sees after."""

from __future__ import annotations

from langgraph.types import RetryPolicy

from automind.application.usage import BudgetExceeded

_TRANSIENT_NAMES = ("APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
                    "ServiceUnavailableError", "ServiceUnavailable", "ProviderUnavailable", "ConnectError",
                    "ReadTimeout", "ConnectTimeout", "RemoteProtocolError")  # fmt: skip
_TRANSIENT_TEXT = ("503", "502", "504", "UNAVAILABLE", "high demand", "overloaded", "RESOURCE_EXHAUSTED", "429",
                   "Connection reset", "timed out")  # fmt: skip


def transient_provider_error(e: BaseException) -> bool:
    """A failure that may pass on a second try (network, 429, 5xx); never a budget stop or a bug."""
    if isinstance(e, BudgetExceeded | ValueError | TypeError | KeyError | AttributeError):
        return False
    names = {t.__name__ for t in type(e).__mro__}
    if names & set(_TRANSIENT_NAMES):
        return True
    raw = f"{type(e).__name__}: {e}"
    return any(k in raw for k in _TRANSIENT_TEXT)


LLM_RETRY = RetryPolicy(max_attempts=2, initial_interval=1.0, jitter=True, retry_on=transient_provider_error)
