"""Transient provider errors (spec 007 FR-028): what an LLM node retries once (the kinds are named in
`shared/contracts/provider_failure.py`; a budget stop or a bug is never retried)."""

from __future__ import annotations

from langgraph.types import RetryPolicy

from automind.shared.contracts.provider_failure import TRANSIENT, classify


def transient_provider_error(e: BaseException) -> bool:
    """A failure that may pass on a second try: quota, rate limit, overload, network."""
    return classify(e) in TRANSIENT


LLM_RETRY = RetryPolicy(max_attempts=2, initial_interval=1.0, jitter=True, retry_on=transient_provider_error)
