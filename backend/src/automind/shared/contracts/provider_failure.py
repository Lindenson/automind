"""What went wrong with a model provider: the one classifier every caller uses (code-shape "States, not words" 3).

A failure is named by its type first (the client libraries' exception classes, by name so that no SDK is imported
here); only where a provider says nothing but text ("503 UNAVAILABLE", "RESOURCE_EXHAUSTED") does the text decide,
from the one table `_BY_TEXT`. Callers ask a question of the result, never of the text:

- the gateway skips a model whose quota is used up (`QUOTA`, for `quota_reset_s`) or that is overloaded
  (`OVERLOAD`, for a short pause);
- an LLM node retries a `transient` failure once (chat/dialog/retry.py);
- the turn runner tells the user the AI service is busy when `provider_busy`;
- the usage callback labels the `llm_errors` metric with the failure's value.
"""

from __future__ import annotations

import re
from enum import StrEnum

from automind.shared.metering.usage import BudgetExceeded


class ProviderFailure(StrEnum):
    """The kind of a model call's failure."""

    QUOTA = "quota"  # a daily or plan quota used up: the model is skipped until it resets
    RATE_LIMIT = "rate_limit"  # a per-minute burst limit or HTTP 429: the client's own retries handle it
    OVERLOAD = "overload"  # the provider is overloaded or briefly down (503, 529, 500 INTERNAL, "high demand")
    NETWORK = "network"  # the connection failed or timed out (502, 504, reset, the HTTP client's errors)
    OTHER = "other"  # not a provider failure: a bug, a bad request, a budget stop


class ProviderUnavailable(RuntimeError):
    """Every model of a role is overloaded or out of quota (raised by the gateway; the user sees a plain message)."""


TRANSIENT = frozenset({ProviderFailure.QUOTA, ProviderFailure.RATE_LIMIT, ProviderFailure.OVERLOAD,
                       ProviderFailure.NETWORK})  # fmt: skip
BUSY = frozenset({ProviderFailure.QUOTA, ProviderFailure.RATE_LIMIT, ProviderFailure.OVERLOAD})

# Exception classes of the provider and HTTP clients (openai, anthropic, google, httpx), matched along the MRO.
_BY_TYPE: dict[str, ProviderFailure] = {
    "ProviderUnavailable": ProviderFailure.OVERLOAD,
    "RateLimitError": ProviderFailure.RATE_LIMIT,
    "InternalServerError": ProviderFailure.OVERLOAD,
    "ServiceUnavailableError": ProviderFailure.OVERLOAD,
    "ServiceUnavailable": ProviderFailure.OVERLOAD,
    "APIConnectionError": ProviderFailure.NETWORK,
    "APITimeoutError": ProviderFailure.NETWORK,
    "ConnectError": ProviderFailure.NETWORK,
    "ConnectTimeout": ProviderFailure.NETWORK,
    "ReadTimeout": ProviderFailure.NETWORK,
    "RemoteProtocolError": ProviderFailure.NETWORK,
}
# The text fallback, in this order (a quota text that also says 503 is a quota).
_BY_TEXT: tuple[tuple[ProviderFailure, tuple[str, ...]], ...] = (
    (ProviderFailure.QUOTA, ("RESOURCE_EXHAUSTED", "insufficient_quota")),
    (
        ProviderFailure.OVERLOAD,
        ("503", "UNAVAILABLE", "high demand", "overloaded", "Overloaded", "529", "500 INTERNAL"),
    ),  # fmt: skip
    (ProviderFailure.RATE_LIMIT, ("429", "RateLimit")),
    (ProviderFailure.NETWORK, ("502", "504", "Connection reset", "timed out")),
)
_PER_MINUTE = re.compile(r"PerMinute|per minute", re.I)  # a quota text naming a per-minute limit: a burst
_RETRY_IN = re.compile(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.I)  # "Please retry in 1h2m3.5s"
_NEVER = (BudgetExceeded, ValueError, TypeError, KeyError, AttributeError)  # our own stops and bugs
QUOTA_DEFAULT_RESET_S = 3600.0


def classify(error: BaseException) -> ProviderFailure:
    """The kind of `error`: by its class first, then by the provider's text."""
    if isinstance(error, _NEVER):
        return ProviderFailure.OTHER
    for cls in type(error).__mro__:
        if cls.__name__ in _BY_TYPE:
            return _BY_TYPE[cls.__name__]
    text = f"{type(error).__name__}: {error}"
    for failure, words in _BY_TEXT:
        if any(w in text for w in words):
            return _burst_or(failure, text)
    return ProviderFailure.OTHER


def quota_reset_s(error: BaseException) -> float | None:
    """Seconds until a used-up quota resets (the provider's "retry in …", else an hour); None for other failures."""
    if classify(error) is not ProviderFailure.QUOTA:
        return None
    m = _RETRY_IN.search(str(error))
    if m and any(m.groups()):
        h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + sec
    return QUOTA_DEFAULT_RESET_S


def _burst_or(failure: ProviderFailure, text: str) -> ProviderFailure:
    if failure is ProviderFailure.QUOTA and _PER_MINUTE.search(text):
        return ProviderFailure.RATE_LIMIT
    return failure
