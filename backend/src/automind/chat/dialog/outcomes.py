"""What a turn leaves for its outcome (spec 010 US1): the nodes visited and the signals noted on the way.

The runner opens a per-turn record (a context variable) before the graph runs; nodes note signals with `note()`,
the graph wrapper records each node with `visit()`. Nothing here changes a turn's behaviour.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

_TURN: ContextVar[dict[str, Any] | None] = ContextVar("turn_outcome_record", default=None)

COST_LIMITS = ("llm_calls", "search_calls", "cost", "daily_cap", "turn_cost")
PROCESS_LIMITS = ("turn_timeout", "graph_steps")
NODATA_STATUSES = ("MISSING", "UNAVAILABLE")


def open_record() -> Any:
    return _TURN.set({"path": [], "signals": {}})


def close_record(token: Any) -> dict[str, Any]:
    rec = _TURN.get() or {"path": [], "signals": {}}
    _TURN.reset(token)
    return rec


def current() -> dict[str, Any]:
    return _TURN.get() or {"path": [], "signals": {}}


def note(key: str, amount: float = 1.0) -> None:
    rec = _TURN.get()
    if rec is not None and amount:
        rec["signals"][key] = float(rec["signals"].get(key, 0)) + amount


def visit(node: str) -> None:
    rec = _TURN.get()
    if rec is not None and (not rec["path"] or rec["path"][-1] != node):
        rec["path"].append(node)


def traced(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a graph node so its name is recorded; the signature seen by LangGraph stays the original."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def anode(*args: Any, **kwargs: Any) -> Any:
            visit(name)
            return await fn(*args, **kwargs)

        return anode

    @functools.wraps(fn)
    def node(*args: Any, **kwargs: Any) -> Any:
        visit(name)
        return fn(*args, **kwargs)

    return node


def nodata_items(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for b in blocks:
        if b.get("type") != "data_panel":
            continue
        for car in b.get("cars") or []:
            for row in car.get("areas") or []:
                if row.get("status") in NODATA_STATUSES:
                    out.append({"car": str(car.get("car_key") or ""), "area": str(row.get("area") or "")})
    return out


def final_signals(final: dict[str, Any], limits_reached: list[str], provider_down: bool = False) -> dict[str, Any]:
    """Signals of the turn itself, from its final state and the limits it hit."""
    sig: dict[str, Any] = {}
    nod = nodata_items(list(final.get("blocks") or []))
    if nod:
        sig["no_data"] = len(nod)
        sig["nodata_items"] = nod[:20]
    if any(x in PROCESS_LIMITS for x in limits_reached) or provider_down:
        sig["process_failure"] = 1
    if any(x in COST_LIMITS for x in limits_reached) or final.get("research_declined"):
        sig["too_costly"] = 1
    return sig


def previous_signals(final: dict[str, Any]) -> tuple[str | None, dict[str, float]]:
    """What this turn says about the previous answer: the relation and a corrected car."""
    i = final.get("interpretation") or {}
    relation = i.get("relation") if isinstance(i, dict) else None
    delta = (i.get("delta") or {}) if isinstance(i, dict) else {}
    sig: dict[str, float] = {}
    if delta.get("replace_cars"):
        sig["wrong_car"] = 1.0
    if relation == "complaint" or final.get("request_kind") == "critique":
        sig["complaint"] = 1.0
    preset = final.get("preset") or {}
    if preset.get("kind") == "car_edit":  # a structured "change the car" (spec 010 US10)
        sig["wrong_car"] = 1.0
    return relation, sig
