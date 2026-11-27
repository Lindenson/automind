"""The `@node` decorator (spec 014 T101, T105, T107): a missing required key, an unknown or foreign key, a result
that is not the node's Out, an append-only key that loses items — an error in strict mode (the tests' default),
a log line and a metric in production; only the keys a node set are written, values as given."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SkipValidation, ValidationError

from automind.chat.dialog.contract import ContractError, NodeIn, NodeOut, Retry, ViolationKind, node
from automind.chat.dialog.graph import contracted_nodes
from automind.chat.dialog.retry import LLM_RETRY
from automind.chat.dialog.tracing import close_record, open_record
from automind.shared.infrastructure.config.settings import settings
from automind.shared.infrastructure.metrics import prom

RUNTIME: Any = SimpleNamespace(context=object())  # the bodies below never touch the context


class NeedsDecision(NodeIn):
    decision: SkipValidation[dict[str, object]]
    language: str | None = "en"


class Replies(NodeOut):
    reply_text: str
    blocks: SkipValidation[list[dict[str, object]]] = []


class Notices(NodeIn):
    notices: SkipValidation[list[dict[str, object]]] = []


class NoticesOut(NodeOut):
    notices: SkipValidation[list[dict[str, object]]]


@node("general", reads=NeedsDecision, writes=Replies)
async def _reply(inp: NeedsDecision, c: object) -> Replies:
    return Replies(reply_text=f"{inp.language}:{inp.decision.get('kind')}")


@pytest.fixture
def lenient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings(), "contract_strict", False)


def _violations(node_id: str, key: str, kind: ViolationKind) -> float:
    return prom.GRAPH_CONTRACT_VIOLATIONS.labels(node=node_id, key=key, kind=str(kind))._value.get()


async def test_a_node_gets_typed_input_and_writes_only_what_it_set() -> None:
    token = open_record()
    update = await _reply({"decision": {"kind": "ASK"}, "language": "es", "hops": 3}, RUNTIME)
    assert close_record(token)["path"] == ["general"]  # the node is recorded in the turn's path
    assert update == {"reply_text": "es:ASK"}  # `blocks` has a default and was not set: not written


async def test_a_missing_required_key_fails_with_the_node_and_the_key() -> None:
    with pytest.raises(ContractError) as e:
        await _reply({"language": "es"}, RUNTIME)
    assert (e.value.node, e.value.key, e.value.kind) == ("general", "decision", ViolationKind.MISSING)


@pytest.mark.usefixtures("lenient")
async def test_in_production_a_violation_is_logged_and_counted_and_the_turn_goes_on() -> None:
    before = _violations("general", "decision", ViolationKind.MISSING)
    with pytest.raises(AttributeError):  # the body runs on the input as found, like the `state[...]` it replaced
        await _reply({"language": "es"}, RUNTIME)
    assert _violations("general", "decision", ViolationKind.MISSING) == before + 1


def test_a_write_of_a_key_the_node_does_not_own_is_refused_at_declaration() -> None:
    with pytest.raises(ContractError) as e:
        node("ask", reads=NodeIn, writes=NoticesOut)(_notices)  # notices: identify, assess, … — not ask
    assert (e.value.key, e.value.kind) == ("notices", ViolationKind.FOREIGN)


def test_a_key_outside_the_turn_state_is_refused_at_declaration() -> None:
    class AdHoc(NodeIn):
        mood: str = ""

    with pytest.raises(ContractError) as e:
        node("general", reads=AdHoc, writes=Replies)(_any)
    assert (e.value.key, e.value.kind) == ("mood", ViolationKind.UNKNOWN)


def test_an_out_model_refuses_an_extra_key() -> None:
    with pytest.raises(ValidationError):
        Replies.model_validate({"reply_text": "x", "mood": "ok"})


async def test_a_body_returning_a_plain_dict_breaks_the_contract() -> None:
    plain = node("general", reads=NodeIn, writes=Replies)(_plain)
    with pytest.raises(ContractError) as e:
        await plain({}, RUNTIME)
    assert e.value.kind is ViolationKind.TYPE


async def test_an_append_only_key_keeps_every_earlier_item() -> None:
    keeps = node("identify", reads=Notices, writes=NoticesOut)(_notices)
    first, second = {"text": "a"}, {"text": "b"}
    assert (await keeps({"notices": [first]}, RUNTIME))["notices"] == [first, {"text": "new"}]
    drops = node("identify", reads=Notices, writes=NoticesOut)(_drop_notices)
    with pytest.raises(ContractError) as e:
        await drops({"notices": [first, second]}, RUNTIME)
    assert (e.value.key, e.value.kind) == ("notices", ViolationKind.APPEND)


def test_written_values_are_the_objects_the_node_gave() -> None:
    notices = [{"type": "notice", "text": "x"}]
    assert NoticesOut(notices=notices).update()["notices"] is notices  # no copy, no coercion into the checkpoint


def test_the_retry_setting_is_named_and_only_the_model_nodes_retry() -> None:
    assert Retry.PROVIDER.policy() is LLM_RETRY and Retry.NONE.policy() is None
    retried = {n.name for n in contracted_nodes() if n.retry is Retry.PROVIDER}
    assert retried == {"interpret", "general", "answer", "report"}  # as the former (id, fn, True) tuples


async def _notices(inp: Notices, c: object) -> NoticesOut:
    return NoticesOut(notices=[*inp.notices, {"text": "new"}])


async def _drop_notices(inp: Notices, c: object) -> NoticesOut:
    return NoticesOut(notices=inp.notices[1:])


async def _plain(inp: NodeIn, c: object) -> Any:
    return {"reply_text": "x"}


async def _any(inp: Any, c: object) -> Any:
    return Replies(reply_text="")
