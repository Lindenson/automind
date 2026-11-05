"""Spec 010 US7 (T062): lifecycle transitions and hard limits, with a seeded random property test. Pure."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from automind.acquisition.registry.domain.lifecycle import CapState, transition
from automind.acquisition.registry.domain.limits import Guard, check

NOW = datetime(2026, 11, 5, tzinfo=UTC)
CFG = {
    "lifecycle": {
        "promote": {"min_attempts": 8, "min_acc_lb": 0.6, "min_yield": 0.2, "min_signals": 5},
        "degrade": {"min_attempts": 10, "max_acc_lb": 0.45, "max_yield": 0.05, "zero_in_last": 10},
        "recover": {"min_acc_lb": 0.55, "min_yield": 0.15},
        "retire_after_days": 21,
        "retired_retry_days": 30,
    }
}
DENY = ("coches.net",)


def st(status: str, **kw: object) -> CapState:
    base: dict[str, object] = {
        "attempts": 10,
        "acc_lb": 0.7,
        "yield_": 0.5,
        "status_since": NOW - timedelta(days=1),
        "access": "ok",
        "recent": (True,) * 10,
        "signals_w": 6.0,
    }
    base.update(kw)
    return CapState(status=status, **base)  # type: ignore[arg-type]


def test_transitions():
    assert transition(st("discovered"), CFG, NOW).to == "candidate"
    assert transition(st("discovered", access="unknown"), CFG, NOW) is None  # not admitted yet
    assert transition(st("discovered", access="terms_forbid"), CFG, NOW).to == "blocked"
    assert transition(st("candidate"), CFG, NOW).to == "active"
    assert transition(st("candidate", attempts=3), CFG, NOW) is None  # sample too small
    assert transition(st("active", recent=(False,) * 10), CFG, NOW).to == "degraded"
    assert transition(st("active", acc_lb=0.3), CFG, NOW).to == "degraded"
    assert transition(st("degraded"), CFG, NOW).to == "active"
    old = NOW - timedelta(days=30)
    assert transition(st("degraded", acc_lb=0.2, status_since=old), CFG, NOW).to == "retired"
    assert transition(st("retired", status_since=NOW - timedelta(days=31)), CFG, NOW).to == "candidate"
    assert transition(st("blocked", access="ok"), CFG, NOW) is None


def test_no_promotion_on_yield_alone():
    """Spec 011 T063 (FR-012): a candidate above the attempts, accuracy and yield thresholds is not promoted before
    `min_signals` accuracy signals, whatever its yield."""
    assert transition(st("candidate", yield_=0.95, attempts=200, signals_w=4.9), CFG, NOW) is None
    assert transition(st("candidate", yield_=0.95, attempts=200, signals_w=0.0), CFG, NOW) is None
    mv = transition(st("candidate", signals_w=5.0), CFG, NOW)
    assert mv.to == "active" and "5.0 accuracy signals" in mv.reason
    no_cfg = {"lifecycle": {**CFG["lifecycle"], "promote": {"min_attempts": 8, "min_acc_lb": 0.6, "min_yield": 0.2}}}
    assert transition(st("candidate", signals_w=4.0), no_cfg, NOW) is None  # the default minimum is 5


def test_limits():
    g = Guard("km77.com", "ok", False, "active")
    assert check(g, "degraded", DENY) == "apply"
    assert check(Guard("km77.com", "ok", True, "active"), "degraded", DENY) == "held"
    assert check(Guard("coches.net", "ok", False, "candidate"), "active", DENY) == "refused"
    assert check(Guard("x.it", "terms_forbid", False, "candidate"), "active", DENY) == "refused"
    assert check(Guard("x.it", "ok", False, "blocked"), "candidate", DENY) == "refused"
    assert check(Guard("x.it", "ok", False, "blocked"), "candidate", DENY, author="owner") == "apply"
    assert check(Guard("x.it", "ok", False, "active", NOW, False), "degraded", DENY) == "refused"


def test_property_blocked_never_leaves_and_frozen_never_changes():
    rnd = random.Random(10)
    statuses = ("discovered", "candidate", "active", "degraded", "retired", "blocked")
    accesses = ("ok", "unknown", "classifieds", "terms_forbid", "robots_blocked", "paywall")
    for _ in range(1000):
        status, access = rnd.choice(statuses), rnd.choice(accesses)
        domain = rnd.choice(("km77.com", "coches.net", "x.example"))
        frozen = rnd.random() < 0.2
        for _step in range(6):
            s = CapState(
                status,
                rnd.uniform(0, 40),
                rnd.random(),
                rnd.random(),
                NOW - timedelta(days=rnd.uniform(0, 60)),
                access,
                tuple(rnd.random() < 0.5 for _ in range(rnd.randint(0, 15))),
            )
            mv = transition(s, CFG, NOW)
            if mv is None:
                continue
            verdict = check(Guard(domain, access, frozen, status), mv.to, DENY)
            blocked_like = access in ("classifieds", "terms_forbid", "robots_blocked") or domain == "coches.net"
            if verdict == "apply":
                assert status != "blocked", "a blocked capability never leaves blocked"
                assert not frozen, "a frozen source never changes"
                assert not (blocked_like and mv.to != "blocked"), "classifieds/terms/robots never become usable"
                status = mv.to
