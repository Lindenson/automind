"""Per-turn usage accounting and limits (FR-041, FR-042, research R12).

`TurnBudget` counts every LLM call (all roles, including analyst agents) and every search call,
converts them to € with configured prices, and enforces the per-turn limits. It is installed in a
context variable for the duration of a turn so that adapters can charge it without plumbing.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from typing import Any


class BudgetExceeded(RuntimeError):
    """A per-turn limit was reached. `limit` names it for the user-facing notice."""

    def __init__(self, limit: str, message: str) -> None:
        super().__init__(message)
        self.limit = limit


@dataclass(frozen=True)
class Prices:
    """€ per 1M tokens per model, and € per search credit (config/prices.yaml)."""

    llm: dict[str, tuple[float, float]]
    default_llm: tuple[float, float]
    eur_per_credit: float
    credits: dict[str, float]
    provider_query_eur: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_config(cls, d: dict[str, Any]) -> Prices:
        def pair(v: dict[str, Any]) -> tuple[float, float]:
            return float(v["input"]), float(v["output"])

        return cls(
            llm={k: pair(v) for k, v in d.get("llm", {}).items()},
            default_llm=pair(d["default_llm"]),
            eur_per_credit=float(d["search"]["eur_per_credit"]),
            credits={k: float(v) for k, v in d["search"]["credits"].items()},
            provider_query_eur={k: float(v["eur_per_query"]) for k, v in (d["search"].get("providers") or {}).items()},
        )

    def llm_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        p_in, p_out = self.llm.get(model, self.default_llm)
        return (input_tokens * p_in + output_tokens * p_out) / 1_000_000

    def search_cost(self, credits: float) -> float:
        return credits * self.eur_per_credit

    def query_cost(self, provider: str) -> float:
        """€ per search query for a provider; Tavily is priced in credits (advanced = 2)."""
        if provider in self.provider_query_eur:
            return self.provider_query_eur[provider]
        return self.search_cost(self.credits.get("search_advanced", 2))


@dataclass(frozen=True)
class Limits:
    max_llm_calls: int = 80
    hard_cap_eur: float = 1.00
    confirm_threshold_eur: float = 0.30
    max_concurrency: int = 4
    job_timeout_s: float = 90.0
    turn_timeout_s: float = 300.0
    daily_cap_eur: float = 0.0  # spend across all chats per day; 0 = no cap (research pauses and asks at it)


@dataclass
class TurnBudget:
    chat_id: str | None
    turn_id: str | None
    prices: Prices
    limits: Limits = field(default_factory=Limits)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    search_calls: int = 0
    identify_search_calls: int = 0  # of search_calls: version look-ups of the intake (not research)
    cost_eur: float = 0.0
    by_role: dict[str, int] = field(default_factory=dict)
    limits_reached: list[str] = field(default_factory=list)
    extensions: int = 0  # the user chose "continue" this many times (each adds one more allowance)
    day_spent_eur: float = 0.0  # spent today by other turns (all chats) before this one
    started: float = field(default_factory=time.monotonic)
    _base: Limits | None = None

    RESEARCH_SHARE = 0.85  # research pauses here, so the answer can still be written with the rest

    def extend(self, times: int) -> None:
        """Give the turn `times` more allowances of calls, cost and time (the user said "continue")."""
        base = self._base or self.limits
        self._base = base
        self.extensions = times
        k = 1 + max(0, times)
        self.limits = replace(base, max_llm_calls=base.max_llm_calls * k, hard_cap_eur=base.hard_cap_eur * k,
                              turn_timeout_s=base.turn_timeout_s * k)  # fmt: skip

    def allow_answer(self, calls: int = 20, eur: float = 0.10) -> None:
        """A small reserve so the answer can be written after research stopped at a limit."""
        base = self.limits
        self.limits = replace(base, max_llm_calls=max(base.max_llm_calls, self.calls + calls),
                              hard_cap_eur=max(base.hard_cap_eur, self.cost_eur + eur))  # fmt: skip

    def research_pause(self) -> str | None:
        """Why research should pause and ask the user (None = go on): calls, cost or time near the limit."""
        lim = self.limits
        if self.calls >= lim.max_llm_calls * self.RESEARCH_SHARE:
            return "calls"
        if self.cost_eur >= lim.hard_cap_eur * self.RESEARCH_SHARE:
            return "cost"
        if time.monotonic() - self.started >= lim.turn_timeout_s * self.RESEARCH_SHARE:
            return "time"
        if self.over_daily_cap():
            return "daily"
        return None

    def over_daily_cap(self) -> bool:
        """Today's spend reached the daily cap; each "continue" allows one more turn allowance past it."""
        cap = (self._base or self.limits).daily_cap_eur
        if not cap:
            return False
        extra = self.extensions * (self._base or self.limits).hard_cap_eur
        return self.day_spent_eur + self.cost_eur >= cap + extra

    def _reached(self, limit: str, message: str) -> BudgetExceeded:
        if limit not in self.limits_reached:
            self.limits_reached.append(limit)
        return BudgetExceeded(limit, message)

    def before_llm_call(self, role: str) -> None:
        """Called before every model call. Refuses the call when a limit is already reached."""
        if self.calls >= self.limits.max_llm_calls:
            raise self._reached("llm_calls", f"AI call limit of {self.limits.max_llm_calls} per turn reached")
        if self.cost_eur >= self.limits.hard_cap_eur:
            raise self._reached("cost_cap", f"cost cap of €{self.limits.hard_cap_eur:.2f} per turn reached")
        self.calls += 1
        self.by_role[role] = self.by_role.get(role, 0) + 1

    def after_llm_call(self, model: str, input_tokens: int, output_tokens: int) -> float:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        cost = self.prices.llm_cost(model, input_tokens, output_tokens)
        self.cost_eur += cost
        return cost

    def before_search(self, credits: float) -> None:
        if self.cost_eur + self.prices.search_cost(credits) > self.limits.hard_cap_eur:
            raise self._reached("cost_cap", f"cost cap of €{self.limits.hard_cap_eur:.2f} per turn reached")

    def after_search(self, credits: float) -> float:
        return self.after_search_eur(self.prices.search_cost(credits))

    def before_search_eur(self, eur: float) -> None:
        if self.cost_eur + eur > self.limits.hard_cap_eur:
            raise self._reached("cost_cap", f"cost cap of €{self.limits.hard_cap_eur:.2f} per turn reached")

    def after_search_eur(self, eur: float) -> float:
        self.search_calls += 1
        self.cost_eur += eur
        return eur

    def restore(self, usage: dict[str, Any] | None) -> None:
        """Continue counting from a stored snapshot (a turn resumed after a confirmation or a restart)."""
        u = usage or {}
        self.calls = int(u.get("llm_calls") or 0)
        self.input_tokens = int(u.get("input_tokens") or 0)
        self.output_tokens = int(u.get("output_tokens") or 0)
        self.search_calls = int(u.get("search_calls") or 0)
        self.identify_search_calls = int(u.get("identify_search_calls") or 0)
        self.cost_eur = float(u.get("cost_eur") or 0.0)

    def snapshot(self) -> dict[str, Any]:
        """The `usage` payload shown to the user (contracts/chat-protocol.md)."""
        return {
            "llm_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "search_calls": self.search_calls,
            "identify_search_calls": self.identify_search_calls,
            "cost_eur": round(self.cost_eur, 4),
        }


current_budget: ContextVar[TurnBudget | None] = ContextVar("current_budget", default=None)
# (job_id, area) of the research job being run, so usage can be averaged per area (R12, T045)
current_job: ContextVar[tuple[str, str] | None] = ContextVar("current_job", default=None)
