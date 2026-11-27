"""Golden situations (spec 015 T224): passes exported with `policy export <turn_id>` (or built here, see
`make_golden`) are decided again by today's rules; a different decision fails until the fixture is re-exported on
purpose (PL5 does so for the passes its behaviour change touches)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from automind.chat.dialog.policy import Situation, decide
from automind.chat.domain.decision import PolicyConfig

GOLDEN = Path(__file__).parent / "golden"
FIXTURES = [(path, i, fx) for path in sorted(GOLDEN.glob("*.yaml"))
            for i, fx in enumerate(yaml.safe_load(path.read_text(encoding="utf-8")))]  # fmt: skip


def test_there_are_golden_situations() -> None:
    assert len(FIXTURES) >= 3


@pytest.mark.parametrize(("path", "index", "fx"), FIXTURES, ids=[f"{p.stem}[{i}]" for p, i, _ in FIXTURES])
def test_a_golden_situation_is_decided_as_recorded(path: Path, index: int, fx: dict[str, object]) -> None:
    d = decide(Situation.model_validate(fx["situation"]), PolicyConfig.model_validate(fx["config"]))
    expected = fx["expected"]
    assert isinstance(expected, dict)
    assert d.decided_by == expected["decided_by"]
    assert d.action.model_dump(mode="json", exclude={"reason"}) == expected["action"]
