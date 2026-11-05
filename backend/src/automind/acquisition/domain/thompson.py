"""Exploration by Thompson sampling (spec 011 FR-013, research R7). Pure and reproducible.

For each eligible source: a ~ Beta(prior_r + right_w, prior_w + wrong_w), y ~ Beta(1 + accepted, 1 + attempts −
accepted); sampled score a·y − λ·€/attempt. The top `slots` by sample get a try while the day's exploration budget
lasts. The random generator is seeded from the job id and area (`seed_of`), so a job replays the same choice.
Blocked, access-blocked and deny-listed sources are never sampled.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass

BLOCKING_ACCESS = ("classifieds", "terms_forbid", "robots_blocked")


@dataclass(frozen=True)
class Arm:
    domain: str
    status: str
    right_w: float
    wrong_w: float
    prior_r: float
    prior_w: float
    accepted: float
    attempts: float
    cost_per_attempt: float = 0.0
    access: str = "ok"
    market: str = "ANY"


def seed_of(*parts: str) -> int:
    """A stable seed (the same in every process, unlike `hash`)."""
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def _denied(domain: str, deny: Sequence[str]) -> bool:
    d = domain.lower().removeprefix("www.")
    return any(d == x or d.endswith("." + x) for x in deny)


def eligible(a: Arm, deny: Sequence[str] = ()) -> bool:
    return (
        a.status not in ("blocked", "retired", "discovered")
        and a.access not in BLOCKING_ACCESS
        and not _denied(a.domain, deny)
    )


def sample(a: Arm, rng: random.Random, cost_lambda: float = 2.0) -> float:
    acc = rng.betavariate(max(1e-6, a.prior_r + a.right_w), max(1e-6, a.prior_w + a.wrong_w))
    yld = rng.betavariate(1 + max(0.0, a.accepted), 1 + max(0.0, a.attempts - a.accepted))
    return acc * yld - cost_lambda * a.cost_per_attempt


def ranked(arms: Sequence[Arm], seed: int, cost_lambda: float = 2.0, deny: Sequence[str] = ()) -> list[Arm]:
    """Eligible arms in order of one Thompson draw each (drawn in domain order, so input order does not matter)."""
    rng = random.Random(seed)
    pool = sorted((a for a in arms if eligible(a, deny)), key=lambda a: (a.domain, a.market))
    draws = [(sample(a, rng, cost_lambda), a) for a in pool]
    draws.sort(key=lambda d: (-d[0], d[1].domain, d[1].market))
    return [a for _, a in draws]


def explore(
    arms: Sequence[Arm], seed: int, slots: int, budget_eur: float, cost_lambda: float = 2.0, deny: Sequence[str] = ()
) -> list[Arm]:
    """The arms that get an exploration slot: best samples first, while slots and today's budget last."""
    if slots <= 0 or budget_eur <= 0:
        return []
    out: list[Arm] = []
    left = budget_eur
    for a in ranked(arms, seed, cost_lambda, deny):
        if len(out) >= slots:
            break
        if a.cost_per_attempt > left + 1e-12:
            break  # the budget is spent
        out.append(a)
        left -= a.cost_per_attempt
    return out
