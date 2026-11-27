"""Spec 013 T005: the harness itself, without a model — the oracle run (expected labels) goes through every case.

Pins what the old path can score at best, so a change of the harness or of the old path shows here first.
"""

from __future__ import annotations

import asyncio

from tests.eval.understanding.fixture_models import load_fixtures
from tests.eval.understanding.oracle import OracleLLM
from tests.eval.understanding.runner import run
from tests.eval.understanding.schema import load_cases


def test_oracle_run_scores_every_case() -> None:
    cases, fx = load_cases(), load_fixtures()
    results = asyncio.run(run(cases, fx, OracleLLM(cases), quiet=True))
    assert [r.error for r in results if r.error] == []
    scores = [r.score for r in results if r.score is not None]
    reaction = [s.fields["reaction"] for s in scores if "reaction" in s.fields]
    language = [s.fields["language"] for s in scores]
    assert all(reaction), "the oracle's relation maps back to every expected reaction"
    assert sum(language) >= len(language) - 3, "only the button-label cases may keep the guessed language"
