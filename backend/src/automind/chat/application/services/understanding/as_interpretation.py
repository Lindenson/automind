"""The understanding decides (spec 013 S4, T040 first step): a resolved `Intent` of typed words as the
`Interpretation` the rest of the turn applies today — the case changes the understanding read, the request its goals
name, how it took the last answer, the offered option its answer picks. Pure.

Until T041 moves the policy onto `Intent`, the request is the one goal that leads (the first written); a message
with no goal is an intake answer (`compare`) when it answers the open question or states facts, a correction or
critique by its reaction, else chitchat."""

from __future__ import annotations

from typing import Final

from automind.chat.application.services.interpretation.contracts import Interpretation, Relation
from automind.chat.domain.decision import RequestKind
from automind.chat.domain.understanding.intent import AnswerKind, Goal, GoalKind, Intent, Reaction, Understanding

REQUEST_OF: Final[dict[GoalKind, RequestKind]] = {
    GoalKind.COMPARE: "compare",
    GoalKind.SINGLE: "single",
    GoalKind.FOLLOW_UP: "follow_up_question",
    GoalKind.CHANGE_PRIORITIES: "weights_change",
    GoalKind.RESEARCH_MORE: "research_more",
    GoalKind.ASK_GENERAL: "general_question",
    GoalKind.CRITIQUE: "critique",
    GoalKind.STOP: "chitchat",  # T041 gives stop its own action; until then nothing is started
}
RELATION_OF: Final[dict[Reaction, Relation]] = {
    Reaction.THANKS: "thanks",
    Reaction.COMPLAINT: "complaint",
    Reaction.CORRECTION: "correction",
    Reaction.REPHRASE: "rephrase",
}


def as_interpretation(intent: Intent, understood: Understanding) -> Interpretation:
    """The interpretation of `intent` (typed words, after the resolver's rules); `understood` gives the evidence
    words the case checks keep (persona, budget numbers)."""
    goal = intent.goals[0] if intent.goals else None
    answer = intent.answer_to_pending
    return Interpretation(
        request=request_of(intent),
        language=intent.language,
        relation=RELATION_OF[intent.reaction] if intent.reaction else "continues",
        delta=intent.case_changes,
        persona_evidence=understood.persona_evidence,
        constraints_evidence=list(understood.constraints_evidence),
        focus_cars=_focus(goal, "cars"),
        focus_areas=_focus(goal, "areas"),
        option_id=answer.option_id if answer is not None and answer.kind is AnswerKind.OPTION else None,
    )


def request_of(intent: Intent) -> RequestKind:
    """The request the turn runs on today (see the module docstring)."""
    answer = intent.answer_to_pending
    if answer is not None and answer.kind is AnswerKind.CHOOSE_FOR_ME:
        return "choose_for_me"
    if intent.goals:
        return REQUEST_OF[intent.goals[0].kind]
    if answer is not None or _states_facts(intent):
        return "compare"
    if intent.reaction is Reaction.CORRECTION:
        return "correction"
    return "chitchat"


def _states_facts(intent: Intent) -> bool:
    return intent.case_changes != type(intent.case_changes)()


def _focus(goal: Goal | None, what: str) -> list[str]:
    if goal is None or goal.kind not in (GoalKind.RESEARCH_MORE, GoalKind.CRITIQUE):
        return []
    return list(goal.focus_cars if what == "cars" else goal.focus_areas)
