"""Which sources a research job uses for an area (spec 010 US6-US8, spec 011 R7). Pure.

- `rank_queryable` — sources worth a `site:` query: active by score before open candidates, markets in the caller's
  order, one entry per domain.
- `ordered_active` — the plan's sources with autonomy on: active before degraded, by score, one per domain.
- `pick_candidates` — the candidates that get an exploration slot, drawn by Thompson sampling within today's budget.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from automind.acquisition.domain import thompson
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.domain.model import ACCESS_BLOCKING, CapabilityStatus
from automind.acquisition.registry.domain.records import CapabilityView

DOMAIN = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/[\w./-]*)?$")  # survey text that is not a domain is skipped
NO_SEED_PRIORITY = 9
EXTRA_DRAWS = 4  # draws beyond the slots, so a domain drawn twice (two markets) still fills them


@dataclass(frozen=True)
class Exploration:
    """What the draw of candidates depends on besides the capabilities."""

    slots: int
    budget_eur: float
    seed: int


def rank_queryable(rows: Sequence[CapabilityView], markets: Sequence[str], limit: int) -> list[CapabilityView]:
    """Sources for `site:` queries: active (by score) before candidates whose access is "ok" (by score, then seed
    priority); within a status the markets keep the caller's order. Never access-blocked sources or non-domains."""
    order = {m: i for i, m in enumerate(markets)}
    usable = [
        r for r in rows
        if DOMAIN.match(r.domain) and r.access not in ACCESS_BLOCKING
        and (r.status == CapabilityStatus.ACTIVE or (r.status == CapabilityStatus.CANDIDATE and r.access == "ok"))
    ]  # fmt: skip
    usable.sort(key=lambda r: (r.status != CapabilityStatus.ACTIVE, order.get(r.market, len(order)), -r.score,
                               r.priority_seed or NO_SEED_PRIORITY, r.domain))  # fmt: skip
    return _one_per_domain(usable, limit)


def ordered_active(rows: Sequence[CapabilityView]) -> list[CapabilityView]:
    """Active and degraded capabilities: active first, best score first, then seed priority; one per domain."""
    usable = [r for r in rows if r.status in (CapabilityStatus.ACTIVE, CapabilityStatus.DEGRADED)]
    usable.sort(
        key=lambda r: (r.status != CapabilityStatus.ACTIVE, -r.score, r.priority_seed or NO_SEED_PRIORITY, r.domain)
    )
    return _one_per_domain(usable, len(usable))


def blocked_domains(rows: Sequence[CapabilityView]) -> list[str]:
    """The domains research must skip for the area."""
    return sorted({r.domain for r in rows if r.status == CapabilityStatus.BLOCKED})


def exploration(cfg: RegistryConfig, spent_today_eur: float, seed: int) -> Exploration:
    """The slots of a job (the smaller of the two settings) and what is left of today's exploration budget."""
    slots = min(cfg.candidate_slots, cfg.explore_max_candidates)
    return Exploration(slots, cfg.explore_eur_per_day - spent_today_eur, seed)


def pick_candidates(rows: Sequence[CapabilityView], taken: set[str], cfg: RegistryConfig,
                    how: Exploration) -> list[CapabilityView]:  # fmt: skip
    """Candidates not in `taken`, drawn by Thompson sampling (reproducible for a seed); one per domain."""
    by_key = {(r.domain, r.market): r for r in rows if r.status == CapabilityStatus.CANDIDATE and r.domain not in taken}
    arms = [_arm(r, cfg) for r in by_key.values()]
    picked: list[CapabilityView] = []
    for a in thompson.explore(arms, how.seed, how.slots + EXTRA_DRAWS, how.budget_eur, cfg.score.cost_lambda):
        if len(picked) >= how.slots:
            break
        if all(p.domain != a.domain for p in picked):
            picked.append(by_key[(a.domain, a.market)])
    return picked


def _one_per_domain(rows: list[CapabilityView], limit: int) -> list[CapabilityView]:
    out: list[CapabilityView] = []
    for r in rows:
        if len(out) >= limit:
            break
        if all(p.domain != r.domain for p in out):
            out.append(r)
    return out


def _arm(r: CapabilityView, cfg: RegistryConfig) -> thompson.Arm:
    prior_r, prior_w = cfg.score.prior(r.source_type)
    return thompson.Arm(
        domain=r.domain, status=r.status, right_w=r.right_w, wrong_w=r.wrong_w, prior_r=prior_r, prior_w=prior_w,
        accepted=r.accepted, attempts=r.attempts,
        cost_per_attempt=r.cost_eur / r.attempts if r.attempts > 0 else 0.0, access=r.access or "ok",
        market=r.market,
    )  # fmt: skip
