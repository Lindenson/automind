"""Prometheus metrics of the dialog's policy (spec 015 D5, D6). Every function never raises: a metric must not break
a turn.

- `automind_policy_decisions_total{rule,action}` — passes by the rule that decided and the action;
- `automind_policy_pass_limit_total` — passes decided by the pass limit (the policy looped; alert
  `AutomindPolicyPassLimit`);
- `automind_policy_passes_per_turn` — passes of a finished turn;
- `automind_policy_input_errors_total{field}` — situations that broke an invariant (lenient mode);
- `automind_policy_record_errors_total` — passes the `DecisionLog` could not store.
"""

from __future__ import annotations

import logging

from prometheus_client import Counter, Histogram

log = logging.getLogger(__name__)

P = "automind_"
DECISIONS = Counter(P + "policy_decisions_total", "Policy passes by deciding rule and action", ["rule", "action"])
PASS_LIMIT = Counter(P + "policy_pass_limit_total", "Policy passes decided by the pass limit")
PASSES = Histogram(P + "policy_passes_per_turn", "Policy passes in one finished turn", buckets=(1, 2, 3, 4, 5, 6, 8, 9))
INPUT_ERRORS = Counter(P + "policy_input_errors_total", "Policy situations that broke an invariant, by field",
                       ["field"])  # fmt: skip
RECORD_ERRORS = Counter(P + "policy_record_errors_total", "Policy passes that could not be recorded")


def decided(rule: str, action: str, *, pass_limit: bool) -> None:
    """One pass decided by `rule` with `action`; `pass_limit`: the limit pass."""
    try:
        DECISIONS.labels(rule=rule, action=action).inc()
        if pass_limit:
            PASS_LIMIT.inc()
    except Exception:  # noqa: BLE001
        log.debug("policy decision not counted", exc_info=True)


def passes(n: int) -> None:
    """The policy passes of a finished turn."""
    try:
        PASSES.observe(max(0, n))
    except Exception:  # noqa: BLE001
        log.debug("policy passes not observed", exc_info=True)


def input_error(field: str) -> None:
    """A situation broke the invariant on `field`."""
    try:
        INPUT_ERRORS.labels(field=field).inc()
    except Exception:  # noqa: BLE001
        log.debug("policy input error not counted", exc_info=True)


def record_error() -> None:
    """A pass could not be recorded."""
    try:
        RECORD_ERRORS.inc()
    except Exception:  # noqa: BLE001
        log.debug("policy record error not counted", exc_info=True)


def metric_names() -> set[str]:
    """Every sample name exported here (for the rules test)."""
    counters = {c._name + "_total" for c in (DECISIONS, PASS_LIMIT, INPUT_ERRORS, RECORD_ERRORS)}  # noqa: SLF001
    base = PASSES._name  # noqa: SLF001
    return counters | {base + "_bucket", base + "_sum", base + "_count"}
