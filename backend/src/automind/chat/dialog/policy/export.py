"""A recorded pass as a golden fixture (spec 015 T223, T224): the full situation with the person's words and region
masked, the config and the expected decision. Fixtures in `tests/unit/chat/dialog/policy/golden/` are decided again
by every test run. Pure."""

from __future__ import annotations

from typing import Final

from automind.chat.dialog.policy.record import situation_of
from automind.chat.domain.case import CaseFile
from automind.chat.domain.decision import DecisionRecord
from automind.shared.contracts.json import JsonObject

MASK: Final = "<masked>"
MASKED_KEYS: Final = frozenset({"request_text", "evidence", "region", "region_code"})  # the person's words, where


def fixture(rec: DecisionRecord, case: CaseFile, config: JsonObject) -> JsonObject:
    """The pass as a fixture: `situation` (case masked), `config`, and `expected` (`decided_by`, the action without
    its free-text reason)."""
    situation = situation_of(rec, mask(case)).model_dump(mode="json")
    return {
        "turn_id": rec.turn_id, "pass_no": rec.pass_no, "rules_version": rec.rules_version, "config": config,
        "situation": situation,
        "expected": {"decided_by": rec.decided_by, "action": {k: v for k, v in rec.action.items() if k != "reason"}},
    }  # fmt: skip


def mask(case: CaseFile) -> CaseFile:
    """`case` with every string under a masked key replaced by `MASK` (the person's words and region)."""
    return CaseFile.model_validate(_mask(case.model_dump(mode="json"), masked=False))


def _mask(value: object, *, masked: bool) -> object:
    if isinstance(value, dict):
        return {k: _mask(v, masked=masked or k in MASKED_KEYS) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, masked=masked) for v in value]
    return MASK if masked and isinstance(value, str) else value
