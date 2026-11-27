"""The IntentResolver (spec 013 T032): typed words through every rule, buttons by their ids, the system's turn
never a person's intent."""

from __future__ import annotations

from automind.chat.application.services.understanding.resolver import IntentResolver, system_intent
from automind.chat.domain.understanding.intent import AnswerKind, GoalKind, IntentSource, UiAction, UiActionKind

from .builder import CARD, ENGINE_Q, ctx, question, understanding


def test_words_go_through_every_rule_in_order() -> None:
    yes = {"pending_id": question(ENGINE_Q).id, "kind": "yes", "evidence": "useless"}
    u = understanding(language="en", reaction="complaint", answer_to_pending=yes)
    i = IntentResolver().from_text(u, ctx(p=ENGINE_Q, text="useless", earlier=["сравни две машины пожалуйста"]))
    assert i.source is IntentSource.TEXT and i.answer_to_pending is None and i.language == "ru"
    assert [o.rule for o in i.overrides] == ["complaint_is_not_an_answer", "language_hysteresis"]


def test_a_tapped_chip_answers_by_its_id() -> None:
    action = UiAction(kind=UiActionKind.PICK_OPTION, option_id="q:car#1:ENGINE:1")
    i = IntentResolver().from_ui(action, ctx(p=ENGINE_Q), "ru")
    assert i.source is IntentSource.UI and i.answer_to_pending is not None
    assert (i.answer_to_pending.kind, i.answer_to_pending.option_id) == (AnswerKind.OPTION, "q:car#1:ENGINE:1")
    assert i.answer_to_pending.pending_id == question(ENGINE_Q).id and i.overrides[0].rule == "option_from_ui"
    tap = UiAction(kind=UiActionKind.PICK_OPTION, option_id="choose")
    choose = IntentResolver().from_ui(tap, ctx(p=ENGINE_Q), "ru")
    assert choose.answer_to_pending.kind is AnswerKind.CHOOSE_FOR_ME  # type: ignore[union-attr]


def test_a_button_of_a_question_no_longer_open_is_dropped() -> None:
    old = UiAction(kind=UiActionKind.CONFIRM, pending_id="q-gone")
    i = IntentResolver().from_ui(old, ctx(p=CARD), "es")
    assert i.answer_to_pending is None and [o.rule for o in i.overrides] == ["option_from_ui", "stale_pending"]


def test_find_it_is_the_goal_research_more() -> None:
    action = UiAction(kind=UiActionKind.RESEARCH_MORE, focus_cars=["car#2"], focus_areas=["price"])
    i = IntentResolver().from_ui(action, ctx(), "en")
    assert [(g.kind, g.focus_cars, g.focus_areas) for g in i.goals] == [(GoalKind.RESEARCH_MORE, ["car#2"], ["price"])]


def test_a_panel_edit_and_a_saved_report_carry_no_goal() -> None:
    assert IntentResolver().from_ui(UiAction(kind=UiActionKind.PANEL_EDIT), ctx(), "en").goals == []
    s = system_intent("ru")
    assert s.source is IntentSource.SYSTEM and s.goals == [] and s.answer_to_pending is None
