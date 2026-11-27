"""The Out builders of interpret, apply_delta and assess write what the services' former `to_state()` wrote (spec
014 T102: they replace `ReadState`/`AppliedState`/`AssessedState`), except `request_kind`, which only apply_delta
writes now (T103: interpret's request is inside its interpretation)."""

from __future__ import annotations

from automind.chat.application.services.assessment.contracts import Planned
from automind.chat.application.services.identification.contracts import Assessment
from automind.chat.application.services.interpretation.contracts import Applied, Interpretation, Reading
from automind.chat.application.services.report.blocks.notice import notice
from automind.chat.dialog.nodes.understand_io import ApplyDeltaOut, AssessOut, InterpretOut
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import CarState
from automind.shared.research_order.plan import Job, ResearchPlan


def test_a_question_asked_back_ends_the_turn() -> None:
    asked = InterpretOut.from_reading(Reading(None, "ru", ask="rephrase"), "Please rephrase")
    # the question asked back keeps the person's language (review 2026-11-27: "переформулируйте" came in English)
    assert asked.update() == {"action": "ASK", "done": True, "reply_text": "Please rephrase", "language": "ru"}
    which = InterpretOut.from_reading(Reading(None, "es", ask="which_car"), "¿Qué coche?")
    assert which.update() == {"action": "ASK", "done": True, "reply_text": "¿Qué coche?", "language": "es"}


def test_a_reading_writes_its_interpretation_and_language() -> None:
    i = Interpretation(request="compare", language="en")
    read = InterpretOut.from_reading(Reading(i, "en", picked=True), "")
    assert read.update() == {"interpretation": i.model_dump(mode="json"), "language": "en", "picked": True}
    assert "picked" not in InterpretOut.from_reading(Reading(i, "en"), "").update()


def test_an_applied_message_says_what_changed() -> None:
    applied = Applied(CaseFile(), "choose_for_me", changes=["persona: family"], not_understood=["car#1"], saved=True)
    assert ApplyDeltaOut.from_applied(applied).update() == {
        "request_kind": "choose_for_me", "not_understood": ["car#1"], "case_changed": True,
        "persona_changed": True,
    }  # fmt: skip
    unchanged = Applied(CaseFile(), "compare")
    assert ApplyDeltaOut.from_applied(unchanged).update() == {
        "request_kind": "compare", "not_understood": [], "case_changed": False,
    }  # fmt: skip


def test_an_assessment_writes_the_plan_and_only_new_notices() -> None:
    plan = ResearchPlan(jobs=[Job("a", "v1", "specs")], rounds=1)
    planned = Planned({"a": Assessment(state=CarState())}, plan, "plan-1", 0.01, False, None, [], False)
    earlier = [notice("earlier")]
    out = AssessOut.from_planned(planned, earlier, assessed_version=3).update()
    assert out["research_plan"] == {"jobs": [["a", "v1", "specs", False, False]], "rounds": 1, "key": "plan-1"}
    assert out["cost_estimate"] == 0.01 and out["research_declined"] is False
    assert out["feasibility_pending"] is False and out["assessed_version"] == 3
    assert "notices" not in out and "feasibility" not in out and "case_version" not in out
    warned = Planned({}, plan, "plan-1", 0.0, True, {"results": []}, [notice("old car", "warning")], True)
    out = AssessOut.from_planned(warned, earlier, assessed_version=4).update()
    assert out["notices"] == [*earlier, notice("old car", "warning")] and "case_version" not in out
    assert out["feasibility"] == {"results": []} and out["feasibility_pending"] is True
