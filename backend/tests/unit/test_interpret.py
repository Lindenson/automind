"""Persona changes need words from the current message (no re-derivation from history)."""

from automind.application.interpret import Interpretation, _persona_from_this_message


def interp(evidence):
    return Interpretation.model_validate(
        {
            "request": "follow_up_question",
            "language": "en",
            "persona_evidence": evidence,
            "delta": {"set_persona": {"persona": "PERFORMANCE", "source": "ASKED"}},
        }
    )


def test_persona_kept_when_this_message_states_it():
    assert _persona_from_this_message(interp("race enthusiast"), "the same for a race enthusiast").delta.set_persona


def test_persona_dropped_without_words_in_this_message():
    assert _persona_from_this_message(interp("race enthusiast"), "and now?").delta.set_persona is None
    assert _persona_from_this_message(interp(None), "and now?").delta.set_persona is None


def test_constraint_numbers_must_be_in_this_message():
    from automind.application.interpret import Interpretation, _constraints_from_this_message, numbers_in
    from automind.domain.casefile import Budget, CaseDelta, Needs, RunningLimit

    assert {25000.0, 150.0} <= numbers_in("tengo 25.000 € y no más de 150 al mes")
    assert 25000.0 in numbers_in("бюджет 25 тыс") and 25000.0 in numbers_in("budget 25k")
    i = Interpretation(request="compare", language="en", delta=CaseDelta(
        set_budget=Budget(max_eur=30000, intent="NEW"), set_running_cost_limit=RunningLimit(amount_eur=150),
        set_needs=Needs(passengers=4, towing_kg=1500)))  # fmt: skip
    out = _constraints_from_this_message(i, "a new one, up to 150 a month to run, we are 4")
    assert out.delta.set_budget.max_eur is None and out.delta.set_budget.intent == "NEW"  # 30000 not in the text
    assert out.delta.set_running_cost_limit.amount_eur == 150
    assert out.delta.set_needs.passengers == 4 and out.delta.set_needs.towing_kg is None
