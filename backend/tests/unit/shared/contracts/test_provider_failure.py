"""One classifier of provider failures: by class first, then the provider's text (one table)."""

import pytest

from automind.shared.contracts.provider_failure import ProviderFailure, ProviderUnavailable, classify, quota_reset_s
from automind.shared.metering.usage import BudgetExceeded

F = ProviderFailure


class RateLimitError(Exception):  # the name the openai/anthropic clients use
    pass


class APIConnectionError(Exception):
    pass


@pytest.mark.parametrize(("error", "failure"), [
    (ProviderUnavailable("all busy"), F.OVERLOAD),
    (RateLimitError("slow down"), F.RATE_LIMIT),
    (APIConnectionError("reset"), F.NETWORK),
    (RuntimeError("429 RESOURCE_EXHAUSTED ... PerDay ... retry in 2h"), F.QUOTA),
    (RuntimeError("429 RESOURCE_EXHAUSTED ... PerMinute ... retry in 20s"), F.RATE_LIMIT),
    (RuntimeError("Error code: 429 insufficient_quota"), F.QUOTA),
    (RuntimeError("503 UNAVAILABLE: high demand"), F.OVERLOAD),
    (RuntimeError("Error code: 529 overloaded_error"), F.OVERLOAD),
    (RuntimeError("Error code: 429"), F.RATE_LIMIT),
    (RuntimeError("504 Gateway Timeout"), F.NETWORK),
    (RuntimeError("something else"), F.OTHER),
    (ValueError("503 in a bad schema"), F.OTHER),
    (BudgetExceeded("cost", "503 calls"), F.OTHER),
])  # fmt: skip
def test_classify(error: BaseException, failure: ProviderFailure) -> None:
    assert classify(error) is failure


def test_quota_reset() -> None:
    assert quota_reset_s(RuntimeError("RESOURCE_EXHAUSTED PerDay retry in 1h2m3s")) == 3723
    assert quota_reset_s(RuntimeError("RESOURCE_EXHAUSTED PerDay")) == 3600
    assert quota_reset_s(RuntimeError("503 UNAVAILABLE")) is None
