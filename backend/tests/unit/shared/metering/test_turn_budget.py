"""TurnBudget limits and the usage callback (FR-041, FR-042, SC-012, SC-015)."""

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from automind.shared.infrastructure.llm.usage_callback import UsageCallbackHandler
from automind.shared.metering.usage import BudgetExceeded, Limits, Prices, TurnBudget, current_budget

PRICES = Prices(
    llm={"m:big": (2.0, 10.0)},
    default_llm=(1.0, 1.0),
    eur_per_credit=0.01,
    credits={"search_advanced": 2},
)


def budget(**kw) -> TurnBudget:
    return TurnBudget(chat_id="c", turn_id="t", prices=PRICES, limits=Limits(**kw))


def test_llm_cost_per_million_tokens():
    assert PRICES.llm_cost("m:big", 1_000_000, 100_000) == pytest.approx(2.0 + 1.0)
    assert PRICES.llm_cost("unknown", 500_000, 500_000) == pytest.approx(1.0)


def test_call_limit_blocks_next_call_and_is_named():
    b = budget(max_llm_calls=2)
    b.before_llm_call("interpreter")
    b.before_llm_call("reporter")
    with pytest.raises(BudgetExceeded) as e:
        b.before_llm_call("reporter")
    assert e.value.limit == "llm_calls"
    assert b.limits_reached == ["llm_calls"]
    assert b.by_role == {"interpreter": 1, "reporter": 1}


def test_hard_cap_never_exceeded_by_search_and_blocks_llm_after_cap():
    b = budget(hard_cap_eur=0.05)
    b.after_llm_call("m:big", 0, 4_000)  # €0.04
    b.before_search(0.5)  # +€0.005 -> 0.045, allowed
    b.after_search(0.5)
    with pytest.raises(BudgetExceeded):
        b.before_search(1)  # +€0.01 would exceed 0.05
    b.after_llm_call("m:big", 0, 1_000)  # an in-flight call may land on the cap
    with pytest.raises(BudgetExceeded) as e:
        b.before_llm_call("x")
    assert e.value.limit == "cost_cap"


def test_snapshot_shape():
    b = budget()
    b.before_llm_call("r")
    b.after_llm_call("m:big", 1000, 100)
    b.after_search(2)
    assert b.snapshot() == {
        "llm_calls": 1,
        "input_tokens": 1000,
        "output_tokens": 100,
        "search_calls": 1,
        "identify_search_calls": 0,
        "cost_eur": round(0.002 + 0.001 + 0.02, 4),
    }


class FakeRepo:
    def __init__(self):
        self.rows = []

    async def record_llm(self, **kw):
        self.rows.append(kw)


def _model(handler, n=3):
    msgs = iter(
        [AIMessage(content="ok", usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})] * n
    )
    return GenericFakeChatModel(messages=msgs, callbacks=[handler])


async def test_callback_counts_and_records_every_call():
    repo = FakeRepo()
    model = _model(UsageCallbackHandler("reporter", "m:big", PRICES, repo))
    b = budget()
    token = current_budget.set(b)
    try:
        await model.ainvoke("hi")
        await model.ainvoke("again")
    finally:
        current_budget.reset(token)
    assert b.calls == 2 and b.input_tokens == 200 and b.output_tokens == 20
    assert [r["turn_id"] for r in repo.rows] == ["t", "t"]
    assert sum(r["cost_eur"] for r in repo.rows) == pytest.approx(b.cost_eur)


async def test_callback_aborts_call_over_limit():
    repo = FakeRepo()
    model = _model(UsageCallbackHandler("reporter", "m:big", PRICES, repo))
    token = current_budget.set(budget(max_llm_calls=1))
    try:
        await model.ainvoke("one")
        with pytest.raises(BudgetExceeded):
            await model.ainvoke("two")
    finally:
        current_budget.reset(token)
    assert len(repo.rows) == 1


async def test_failed_call_is_recorded_so_counts_match():
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Boom(GenericFakeChatModel):
        async def _agenerate(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("provider down")

    repo = FakeRepo()
    b = budget()
    token = current_budget.set(b)
    try:
        with pytest.raises(RuntimeError):
            await Boom(messages=iter([]), callbacks=[UsageCallbackHandler("extractor", "m:big", PRICES, repo)]).ainvoke(
                "x"
            )
    finally:
        current_budget.reset(token)
    assert b.calls == 1 == len(repo.rows) and repo.rows[0]["input_tokens"] == 0
