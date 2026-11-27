"""The policy node (spec 015 T213, T214): the case and the last report's fingerprint read once per run however many
passes the turn makes; a broken invariant fails the turn in strict mode, else it is logged and counted and the
policy decides as before."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from automind.chat.application.ports import StoreUnavailable
from automind.chat.dialog.nodes.policy import policy_node
from automind.chat.dialog.policy import PolicyInputError
from automind.chat.dialog.turn.context import TurnContext
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.decision import CarState, DecisionRecord
from automind.shared.infrastructure.metrics import policy as metrics

from .builder import config

CASE = CaseFile(cars=[CaseCar(key="car#1", request_text="Golf", make="Volkswagen", model="Golf")])
FRESH = {"state": CarState(in_catalog=True, data_fresh=True).model_dump()}


@dataclass
class Store:
    """One chat's case (version 4) and its last report's fingerprint, counting the reads."""

    case_reads: int = 0
    fingerprint_reads: int = 0

    async def latest(self, chat_id: str) -> tuple[int, dict[str, Any] | None, str | None]:
        self.case_reads += 1
        return 4, CASE.model_dump(mode="json"), None

    async def last_report_fingerprint(self, chat_id: str) -> str | None:
        self.fingerprint_reads += 1
        return None


@dataclass
class Log:
    """A `DecisionLog` in memory; `down`: every write fails as a store that cannot be reached."""

    down: bool = False
    rows: dict[tuple[str, int], DecisionRecord] = field(default_factory=dict)
    configs: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def record(self, rec: DecisionRecord, config: dict[str, Any]) -> None:
        if self.down:
            raise StoreUnavailable("policy_decisions: OperationalError")
        self.rows[(rec.turn_id, rec.pass_no)] = rec
        self.configs[rec.config_hash] = config


def _runtime(store: Store, *, strict: bool, log: Log | None = None) -> SimpleNamespace:
    cfg = config().model_copy(update={"strict_inputs": strict})
    ports = SimpleNamespace(cases=store, turns=store, policy=cfg, decisions=log)
    return SimpleNamespace(context=TurnContext(ports=ports, chat_id="chat-1", turn_id="turn-1", budget=None))  # type: ignore[arg-type]


def _state(**over: object) -> dict[str, object]:
    return {"request_kind": "compare", "assessments": {"car#1": FRESH}, "assessed_version": 4, "hops": 0, **over}


async def test_every_pass_after_the_first_reads_nothing_from_the_stores() -> None:
    store = Store()
    runtime = _runtime(store, strict=True)
    first = await policy_node(_state(), runtime)
    second = await policy_node(_state(hops=first["hops"]), runtime)
    assert (first["hops"], second["hops"]) == (1, 2) and second["action"] == "REPORT"
    assert (store.case_reads, store.fingerprint_reads) == (1, 1)


async def test_a_broken_invariant_fails_the_turn_in_strict_mode() -> None:
    with pytest.raises(PolicyInputError) as raised:
        await policy_node(_state(assessed_version=3), _runtime(Store(), strict=True))
    assert raised.value.field == "assessed_version"


async def test_a_broken_invariant_is_logged_and_counted_otherwise(caplog: pytest.LogCaptureFixture) -> None:
    counted = metrics.INPUT_ERRORS.labels(field="cars")
    before = counted._value.get()  # noqa: SLF001
    out = await policy_node(_state(assessments={}), _runtime(Store(), strict=False))
    assert out["action"] == "CONFIRM_VARIANTS"  # decided as before PL2: an unassessed car is not in the catalogue
    assert counted._value.get() == before + 1  # noqa: SLF001
    assert "policy.input_error" in caplog.text and "field=cars" in caplog.text


async def test_every_pass_is_recorded_once_by_its_number() -> None:
    log, store = Log(), Store()
    runtime = _runtime(store, strict=True, log=log)
    first = await policy_node(_state(), runtime)
    await policy_node(_state(), runtime)  # the same pass again (a rerun of the node): no duplicate
    await policy_node(_state(hops=first["hops"]), runtime)
    assert sorted(log.rows) == [("turn-1", 1), ("turn-1", 2)]
    rec = log.rows[("turn-1", 2)]
    assert (rec.chat_id, rec.case_version, rec.decided_by, rec.next_node) == ("chat-1", 4, "answer_or_report", "report")
    assert list(log.configs) == [rec.config_hash]


async def test_a_pass_that_cannot_be_recorded_is_logged_and_counted_and_the_turn_goes_on(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = metrics.RECORD_ERRORS._value.get()  # noqa: SLF001
    out = await policy_node(_state(), _runtime(Store(), strict=True, log=Log(down=True)))
    assert out["action"] == "REPORT"
    assert metrics.RECORD_ERRORS._value.get() == before + 1  # noqa: SLF001
    assert any(r.levelname == "ERROR" and "policy.record_failed" in r.message for r in caplog.records)
