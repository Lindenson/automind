"""Spec 013 S4 (T040): a resolved intent as the interpretation the turn applies — the request from the leading goal,
an answer or stated facts as an intake answer, the reaction as the relation, the picked option by its id."""

from __future__ import annotations

import pytest

from automind.chat.application.services.understanding.as_interpretation import as_interpretation, request_of
from automind.chat.domain.understanding.intent import Intent, IntentSource, Understanding


def _intent(**fields: object) -> Intent:
    return Intent.model_validate({"source": IntentSource.TEXT, "language": "ru", **fields})


@pytest.mark.parametrize(
    ("fields", "kind"),
    [
        ({"goals": [{"kind": "compare"}]}, "compare"),
        ({"goals": [{"kind": "follow_up", "question": "а расход?"}]}, "follow_up_question"),
        ({"goals": [{"kind": "ask_general"}, {"kind": "compare"}]}, "general_question"),
        ({"goals": [{"kind": "change_priorities"}]}, "weights_change"),
        ({"goals": [{"kind": "stop"}]}, "chitchat"),
        ({"answer_to_pending": {"pending_id": "q-1", "kind": "value", "evidence": "2019"}}, "compare"),
        ({"answer_to_pending": {"pending_id": "q-1", "kind": "choose_for_me", "evidence": "любой"}}, "choose_for_me"),
        ({"case_changes": {"set_annual_km": 20000}}, "compare"),
        ({"reaction": "correction"}, "correction"),
        ({"reaction": "thanks"}, "chitchat"),
        ({}, "chitchat"),
    ],
)
def test_the_request_of_an_intent(fields: dict[str, object], kind: str) -> None:
    assert request_of(_intent(**fields)) == kind


def test_the_interpretation_carries_the_facts_the_focus_the_relation_and_the_option() -> None:
    intent = _intent(
        goals=[{"kind": "research_more", "focus_cars": ["car#2"], "focus_areas": ["price"]}],
        reaction="complaint",
        answer_to_pending={"pending_id": "q-1", "kind": "option", "option_id": "q:car#2:ENGINE:1", "evidence": "320d"},
        case_changes={"set_annual_km": 20000},
    )
    understood = Understanding.model_validate({"language": "ru", "persona_evidence": "я таксист",
                                               "constraints_evidence": ["20 000 км"]})  # fmt: skip
    i = as_interpretation(intent, understood)
    assert (i.request, i.relation, i.focus_cars, i.focus_areas) == ("research_more", "complaint", ["car#2"], ["price"])
    assert i.option_id == "q:car#2:ENGINE:1" and i.delta.set_annual_km == 20000
    assert i.persona_evidence == "я таксист" and i.constraints_evidence == ["20 000 км"]
    assert "option_id" not in type(i).model_json_schema()["properties"]  # never asked of a model
