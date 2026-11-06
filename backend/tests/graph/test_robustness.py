"""Graph robustness (spec 007 FR-027..FR-029): a hop limit, retried provider errors, a report after a timeout."""

from automind.chat.dialog.retry import transient_provider_error
from automind.chat.domain.case.casefile import CaseCar, CaseFile
from automind.chat.domain.policy import MAX_HOPS, decide
from automind.chat.infrastructure.persistence.repositories import MessageRepo
from tests.fakes.fake_llm import FakeLLM
from tests.golden.runner import load, seed

from .test_rescore import _reported
from .test_weights_recompute import G6, runner, turn


class APIConnectionError(Exception):  # the provider SDK's name: a transient failure
    pass


def test_hop_limit_ends_with_what_the_turn_has():
    car = CaseCar(key="car#1", request_text="Golf", make="VW", model="Golf", variant_id="v1", resolution="CONFIRMED")
    a = decide(CaseFile(cars=[car]), "compare", {}, cost_estimate_eur=None, last_fingerprint=None, hops=MAX_HOPS)
    assert a.kind == "REPORT" and "hop" in a.reason
    bare = CaseFile(cars=[CaseCar(key="car#1", request_text="Golf")])
    b = decide(bare, "compare", {}, cost_estimate_eur=None, last_fingerprint=None, hops=MAX_HOPS)
    assert b.kind == "ANSWER_GENERAL"


def test_what_counts_as_transient():
    assert transient_provider_error(APIConnectionError("reset"))
    assert transient_provider_error(RuntimeError("Error code: 503 - UNAVAILABLE"))
    assert not transient_provider_error(ValueError("bad schema"))
    assert not transient_provider_error(RuntimeError("a bug"))


async def test_a_transient_interpreter_error_is_retried(saver, chat_id):
    await seed(load(G6 / "g6_no_repeat.yaml"))
    llm = FakeLLM()
    llm.queue("interpreter", APIConnectionError("connection reset"))
    for role, outs in turn(1).items():
        llm.queue(role, *outs)
    r = await runner(saver, llm).run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    assert r.status == "DONE" and r.action == "REPORT"


async def test_a_provider_that_stays_down_gives_a_plain_message_not_failed(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    llm.queue("interpreter", APIConnectionError("down"), APIConnectionError("still down"))
    r = await runner(saver, llm).run_turn(chat_id, "and which one is cheaper to run?")
    assert r.status == "DONE" and "Nothing is lost" in (r.reply_text or "")


async def test_after_a_timeout_the_report_comes_from_the_saved_data(saver, chat_id):
    llm = FakeLLM()
    await _reported(saver, chat_id, llm)
    llm.queue("reporter", "From the data already found: the Golf is ahead.")
    r = await runner(saver, llm).run_turn(chat_id, "↻ report", preset={"kind": "report_saved"})
    assert r.action == "REPORT" and r.usage["search_calls"] == 0
    msgs = await MessageRepo().history(chat_id)
    assert not [m for m in msgs if m.role == "user" and m.text.startswith("↻")]  # hidden, like a panel edit
