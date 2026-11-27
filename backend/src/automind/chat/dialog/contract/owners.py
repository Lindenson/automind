"""Who may write each turn-state key (spec 014 D1, T101): the owners registry, read by `@node` and the tests.

Over today's flat keys (step C1) a key may still have several writers; each such key is listed with the step that
gives it one owner (`until`). `load_case` resets every per-turn key (`state.PER_TURN_RESET`) at the start of a turn
and is not listed as their writer (step C3 replaces it with `begin_turn`). `runner` is the turn runner: it writes
the new turn's input before the graph runs. Two keys are append-only for everyone: `notices` (a node writes the
whole list; every earlier notice stays) and `research_results` (a LangGraph reducer appends what a node writes; only
`plan_research` starts it over, with `[RESET]`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from automind.chat.dialog.state import PER_TURN_RESET, RESET

RUNNER: Final = "runner"
RESET_NODE: Final = "load_case"


class Merge(StrEnum):
    """How a write combines with the value before it."""

    REPLACE = "replace"  # the written value is the new value
    APPEND_ALL = "append_all"  # the node writes the whole list; every earlier item must stay in it
    APPEND_DELTA = "append_delta"  # a reducer appends the written items; only a restarter may start with RESET


@dataclass(frozen=True)
class Owner:
    """The writers of one key; `until`: the spec step that leaves one writer (empty: one already); `restarters`:
    who may start an APPEND_DELTA key over."""

    writers: frozenset[str]
    merge: Merge = Merge.REPLACE
    until: str = ""
    restarters: frozenset[str] = frozenset()

    @classmethod
    def one(cls, writer: str) -> Owner:
        """A key with one writer."""
        return cls(frozenset({writer}))

    @classmethod
    def shared(cls, until: str, *writers: str) -> Owner:
        """A key that still has several writers, until the spec step `until`."""
        return cls(frozenset(writers), until=until)


TERMINALS = ("general", "ask", "answer", "report", "alternatives")
APPLIES = ("apply_intake", "apply_variants", "apply_cost", "apply_feasibility", "apply_limit")
PREPARES = ("prepare_intake", "prepare_variants", "prepare_cost", "prepare_feasibility", "prepare_limit")
WAITS = ("wait_intake", "wait_variants", "wait_cost", "wait_feasibility", "wait_limit")

OWNERS: Final[Mapping[str, Owner]] = {
    # input: the runner (load_case repeats the ids)
    "chat_id": Owner(frozenset({RUNNER, RESET_NODE})),
    "turn_id": Owner(frozenset({RUNNER, RESET_NODE})),
    "preset": Owner.one(RUNNER),
    "provider_down": Owner.one(RUNNER),  # the turn ended on a provider failure (turn/execution.py)
    "user_text": Owner.shared("C3: input; typed answers become a new input", RUNNER, *APPLIES),
    # understanding and applying
    "interpretation": Owner.one("interpret"),
    "language": Owner.one("interpret"),
    "picked": Owner.one("interpret"),
    "request_kind": Owner.one(
        "apply_delta"
    ),  # T103: the request as code settled it (interpret's own is in interpretation)
    "case_changed": Owner.one("apply_delta"),
    "persona_changed": Owner.one("apply_delta"),
    "not_understood": Owner.shared("C3: applied (identify narrows it)", "apply_delta", "identify"),
    "done": Owner.shared("C4: Out.next() instead of a router flag", "interpret", "apply_delta"),
    "route": Owner.shared(
        "C4: Out.next() instead of a router flag", "select_candidates", "prepare_variants", *APPLIES
    ),  # fmt: skip
    # C2: the case and its version live in the run's context (TurnContext.case / save_case); the key is only the
    # version the turn started from
    "case_version": Owner.one(RESET_NODE),
    # assessment and decision
    "assessments": Owner.one("assess"),
    "research_plan": Owner.one("assess"),
    "cost_estimate": Owner.one("assess"),
    "feasibility": Owner.one("assess"),
    "decision": Owner.one("policy"),
    "hops": Owner.one("policy"),
    "cost_approved": Owner.shared("015 PL5: ResearchStatus", "apply_cost", "apply_intake"),
    "research_declined": Owner.shared("015 PL5: ResearchStatus", "assess", "apply_cost", "apply_intake"),
    # confirmations
    "confirm_payload": Owner.shared("C3: confirm section of each confirmation", *PREPARES, *APPLIES),
    "resume": Owner.shared("C3: confirm section of each confirmation", *WAITS, *APPLIES),
    # research
    "jobs": Owner.shared("C3: research section", "plan_research", "collect_round", "after_research", "apply_limit"),
    "round": Owner.shared("C3: research section", "plan_research", "collect_round"),
    "limit_hit": Owner.shared("C3: research section", "collect_round", "apply_limit"),
    "limit_extensions": Owner.one("apply_limit"),
    "research_done": Owner.one("after_research"),
    "research_results": Owner(
        frozenset({"plan_research", "research_job"}), Merge.APPEND_DELTA, restarters=frozenset({"plan_research"})
    ),  # fmt: skip
    "notices": Owner(frozenset({"identify", "assess", "prepare_variants", "after_research"}), Merge.APPEND_ALL),
    # reply
    "reply_text": Owner.shared("C3: reply section", "interpret", "apply_delta", "apply_variants", *TERMINALS),
    "blocks": Owner.shared("C3: reply section", *TERMINALS),
    "action": Owner.shared(
        "C3: reply section (the only action)",
        "interpret",
        "apply_delta",
        "policy",
        "prepare_feasibility",
        "apply_variants",
        *TERMINALS,
    ),  # fmt: skip
    "fingerprint": Owner.one("report"),
}


def may_write(node: str, key: str) -> bool:
    """True when `node` may write `key`: a listed writer, or load_case resetting a per-turn key."""
    owner = OWNERS.get(key)
    return owner is not None and (node in owner.writers or (node == RESET_NODE and key in PER_TURN_RESET))


def keeps_earlier(node: str, key: str, before: object, after: object) -> bool:
    """False when a write of an append-only key by `node` drops what was there (`before`); the reset of a turn and
    a restarter starting over are allowed."""
    owner = OWNERS.get(key)
    if owner is None or owner.merge is Merge.REPLACE or node == RESET_NODE:
        return True
    written = list(after) if isinstance(after, Sequence) else []
    if owner.merge is Merge.APPEND_DELTA:
        return not (written and written[0] == RESET) or node in owner.restarters
    earlier = list(before) if isinstance(before, Sequence) else []
    return all(item in written for item in earlier)
