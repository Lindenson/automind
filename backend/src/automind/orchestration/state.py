"""Graph state (data-model §6). The case file itself lives in the DB (versioned); state holds only
workflow data and compact references. One persistent thread per chat, so per-turn keys are reset
by `load_case` at the start of every turn."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

RESET = "__reset__"


def results(old: list[Any] | None, new: list[Any] | None) -> list[Any]:
    """Reducer for parallel research workers: append, or reset when a list starts with RESET."""
    if new and new[0] == RESET:
        return list(new[1:])
    return [*(old or []), *(new or [])]


class TurnState(TypedDict, total=False):
    chat_id: str
    turn_id: str
    user_text: str
    language: str
    request_kind: str
    interpretation: dict[str, Any]
    case_version: int
    assessments: dict[str, dict[str, Any]]  # car key -> {state, candidates, generations}
    decision: dict[str, Any]  # policy Action
    action: str  # final action kind of the turn (recorded on the turn)
    cost_estimate: float | None
    research_plan: dict[str, Any]
    jobs: list[dict[str, Any]]
    round: int
    cost_approved: bool
    research_declined: bool
    research_done: bool
    confirm_payload: dict[str, Any] | None
    resume: dict[str, Any] | None
    research_results: Annotated[list[dict[str, Any]], results]
    notices: list[dict[str, Any]]
    reply_text: str
    blocks: list[dict[str, Any]]
    fingerprint: str | None
    done: bool
    route: str | None
    case_changed: bool
    persona_changed: bool
    limit_hit: dict[str, Any] | None  # research paused at a limit: {reason, jobs} (asks the user, never cancels)
    limit_extensions: int  # how many times the user said "continue" in this turn
    feasibility: dict[str, Any] | None  # {results, fingerprint} from application.feasibility (spec 003 US3)


PER_TURN_RESET: dict[str, Any] = {
    "language": "en",
    "request_kind": None,
    "assessments": {},
    "decision": {},
    "action": None,
    "cost_estimate": None,
    "research_plan": {},
    "jobs": [],
    "round": 0,
    "cost_approved": False,
    "research_declined": False,
    "research_done": False,
    "limit_hit": None,
    "limit_extensions": 0,
    "feasibility": None,
    "confirm_payload": None,
    "resume": None,
    "research_results": [RESET],
    "notices": [],
    "reply_text": "",
    "blocks": [],
    "fingerprint": None,
    "done": False,
    "route": None,
    "case_changed": True,
    "persona_changed": False,
}
