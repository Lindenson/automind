"""Spec 013 T034: the shadow harness runs every case through the new chain without a model error (a fake model that
reads nothing: language only), so a paid run fails only on the model."""

from __future__ import annotations

import asyncio

from automind.chat.domain.understanding.intent import Understanding
from tests.eval.understanding.fixture_models import load_fixtures
from tests.eval.understanding.schema import load_cases
from tests.eval.understanding.shadow import run


class _Nothing:
    """Reads only the language of the message (Cyrillic → ru)."""

    async def structured(self, role: str, schema: type, system: str, user: str) -> Understanding:
        message = user.rsplit("MESSAGE:\n", 1)[1]
        return Understanding(language="ru" if any("а" <= ch <= "я" for ch in message.lower()) else "en")

    async def text(self, role: str, system: str, user: str) -> str:
        raise AssertionError("one structured call per case")


def test_every_case_runs_through_the_new_chain() -> None:
    results = asyncio.run(run(load_cases(), load_fixtures(), _Nothing()))
    assert [r.case.id for r in results if r.error] == []
    assert all(r.score is not None for r in results)
