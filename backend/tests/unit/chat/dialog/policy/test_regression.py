"""Spec 015 T205: the new `decide` decides as the old chain did (`legacy_policy`, frozen at main 422c89a) on random
valid situations — the whole `Action` but its free-text `reason`. `check.sh` runs 500 derandomized examples;
`POLICY_REGRESSION_EXAMPLES=10000` runs the PR's large sample. Removed at PL5, the first behaviour change."""

from __future__ import annotations

import os
from typing import Any

from hypothesis import HealthCheck, given, settings

from . import legacy_policy
from .builder import decision
from .strategies import old_arguments

EXAMPLES = int(os.environ.get("POLICY_REGRESSION_EXAMPLES", "500"))
LARGE = EXAMPLES > 500


@settings(max_examples=EXAMPLES, derandomize=not LARGE, deadline=None, database=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])  # fmt: skip
@given(old_arguments())
def test_new_policy_decides_as_the_old_chain(args: dict[str, Any]) -> None:
    case, request, cars = args.pop("case"), args.pop("request"), args.pop("cars")
    old = legacy_policy.decide(case, request, cars, **args)
    new = decision(case, request, cars, **args).action
    assert new.model_dump(exclude={"reason"}) == old.model_dump(exclude={"reason"})
    assert new.reason == old.reason  # the reasons were ported word for word
