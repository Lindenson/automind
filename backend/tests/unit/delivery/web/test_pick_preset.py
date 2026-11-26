"""Spec 013 T013: a tapped chip's option id becomes a `pick` preset; typed words (old clients) stay words."""

from __future__ import annotations

from automind.chat.domain.turn import PresetKind, preset_kind
from automind.delivery.web.ws import _pick_preset


def test_an_option_id_is_a_pick_preset() -> None:
    p = _pick_preset({"type": "user_message", "text": "E 200", "option_id": "q:car#1:ENGINE:0"})
    assert p is not None and preset_kind(p) is PresetKind.PICK and p["option_id"] == "q:car#1:ENGINE:0"


def test_typed_words_have_no_preset() -> None:
    assert _pick_preset({"type": "user_message", "text": "нет"}) is None
    assert _pick_preset({"type": "user_message", "text": "x", "option_id": "  "}) is None
