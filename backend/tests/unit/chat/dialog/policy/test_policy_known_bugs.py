"""Policy bugs seen live on pre-prod, kept as strict expected failures until the step that fixes them.

A test here that starts passing fails the gate: remove its mark in the PR that fixed it."""

import pytest

from automind.chat.dialog.policy import decide

from .test_policy import NEW_GOLF, case, ready


@pytest.mark.xfail(
    strict=True,
    reason="spec 013 S4 / 015 PL5: chat eb81dd90 turn 2 (2026-11-27 replay of d170b861) — a complaint read as "
    "'correction' with an unchanged case answered 'nothing changed since the last report' before any report existed",
)
def test_correction_without_any_report_is_never_nothing_new():
    c = case(NEW_GOLF)
    a = decide(c, "correction", ready(c), cost_estimate_eur=None, last_fingerprint=None, case_changed=False)
    assert not a.nothing_new
