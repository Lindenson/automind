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
