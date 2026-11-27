"""The IntentResolver (spec 013 T032, understanding-spec §5.1–5.2): an `Understanding` (typed words) or a `UiAction`
(a button) becomes the `Intent`. It is the only place that may correct what was understood; each correction is an
`Override` (`rules`). It does not choose the action (the policy does) and does not change the case. Pure."""

from __future__ import annotations

from automind.chat.application.services.understanding.rules import TEXT_RULES, Context, Rule, stale_pending
from automind.chat.domain.case import CaseDelta
from automind.chat.domain.understanding.intent import (
    AnswerKind,
    Goal,
    GoalKind,
    Intent,
    IntentSource,
    Override,
    PendingAnswer,
    UiAction,
    UiActionKind,
    Understanding,
)

_ANSWER_OF = {UiActionKind.PICK_OPTION: AnswerKind.OPTION, UiActionKind.CONFIRM: AnswerKind.YES,
              UiActionKind.DECLINE: AnswerKind.NO, UiActionKind.CHOOSE_FOR_ME: AnswerKind.CHOOSE_FOR_ME}  # fmt: skip
CHOOSE_ID = "choose"  # the option id of "choose for me" (intake.OptionKind.CHOOSE)


class IntentResolver:
    """Resolves typed words through `rules` (default `TEXT_RULES`, in order) and buttons through `option_from_ui`
    and `stale_pending`."""

    def __init__(self, rules: tuple[Rule, ...] = TEXT_RULES) -> None:
        self.rules = rules

    def from_text(self, u: Understanding, ctx: Context) -> Intent:
        """The intent of a checked `Understanding` (`validate_understanding`), after every rule."""
        i = Intent(source=IntentSource.TEXT, language=u.language, answer_to_pending=u.answer_to_pending,
                   goals=list(u.goals), reaction=u.reaction, case_changes=u.case_changes)  # fmt: skip
        for rule in self.rules:
            i = rule(i, ctx)
        return i

    def from_ui(self, action: UiAction, ctx: Context, language: str, changes: CaseDelta | None = None) -> Intent:
        """The intent of a button: what it answers or asks for, `changes` it carries (a car edit), checked against
        the open question (an answer to a question no longer open is dropped)."""
        i = Intent(source=IntentSource.UI, language=language, case_changes=changes or CaseDelta())
        return stale_pending(option_from_ui(i, action, ctx), ctx)


def system_intent(language: str) -> Intent:
    """The intent of a turn the system starts (the report from saved data): never a person's intent."""
    return Intent(source=IntentSource.SYSTEM, language=language)


def option_from_ui(i: Intent, action: UiAction, ctx: Context) -> Intent:
    """A tapped chip or a confirmation button answers the open question by its option id (no words guessed); "find
    it" is the goal research_more for the cars and areas it names. Old chips send no question id: the open one."""
    kind = _ANSWER_OF.get(action.kind)
    if kind is not None:
        kind = AnswerKind.CHOOSE_FOR_ME if action.option_id == CHOOSE_ID else kind
        open_id = ctx.question.id if ctx.question else "none"
        a = PendingAnswer(pending_id=action.pending_id or open_id, kind=kind,
                          option_id=action.option_id if kind is AnswerKind.OPTION else None,
                          evidence=f"button {action.kind.value}")  # fmt: skip
        o = Override(rule="option_from_ui", field="answer_to_pending", after=a.model_dump(mode="json"),
                     why=f"the button {action.kind.value} answers by its id")  # fmt: skip
        return i.model_copy(update={"answer_to_pending": a, "overrides": [*i.overrides, o]})
    if action.kind is UiActionKind.RESEARCH_MORE:
        g = Goal(kind=GoalKind.RESEARCH_MORE, focus_cars=list(action.focus_cars), focus_areas=list(action.focus_areas))
        o = Override(rule="option_from_ui", field="goals", after=[g.kind.value], why="the button asks to find more")
        return i.model_copy(update={"goals": [g], "overrides": [*i.overrides, o]})
    return i  # edit_car: its changes come with it; panel_edit: a rescore, no goal of the person
