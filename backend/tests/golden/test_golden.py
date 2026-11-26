"""Golden dialogues as regression tests (FR-046, SC-001, SC-002).

Replay (default): `uv run pytest tests/golden`
Live (real models + search, costs money): `uv run pytest tests/golden -m live [--record]`
"""

from pathlib import Path

import pytest

from .runner import GOLDEN_DIR, run_dialogue

DIALOGUES = sorted(Path(GOLDEN_DIR).glob("g*.yaml"))


@pytest.mark.parametrize("path", DIALOGUES, ids=[p.stem for p in DIALOGUES])
async def test_golden_replay(path, saver):
    run = await run_dialogue(path, saver)
    assert not run.failures, "\n".join(run.failures)
    if run.known_bugs:  # spec 013 T003: every `known_bug` turn still fails (strict: a passing one is a failure)
        pytest.xfail("\n".join(run.known_bugs))


@pytest.mark.live
@pytest.mark.parametrize("path", DIALOGUES, ids=[p.stem for p in DIALOGUES])
async def test_golden_live(path, saver, request):
    run = await run_dialogue(path, saver, live=True, record=request.config.getoption("--record"))
    assert not run.failures, "\n".join(run.failures)
    if run.known_bugs:
        pytest.xfail("\n".join(run.known_bugs))
