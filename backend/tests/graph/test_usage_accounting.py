"""Usage shown per turn equals recorded usage across all roles, including analyst agents (FR-042, SC-012)."""

import json
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from automind.application.usage import Prices
from automind.infrastructure.db.repositories import MessageRepo, UsageRepo
from automind.infrastructure.usage_callback import UsageCallbackHandler
from automind.orchestration.graph import build_graph
from automind.orchestration.runner import ChatRunner
from tests.fakes.fake_llm import FakeLLM
from tests.fakes.fixture_search import FixtureSearch
from tests.golden.runner import load, seed

from .conftest import PRICES, budget_factory, make_ports
from .test_research_flow import INTERPRET, fresh_variant, llm_for_research  # noqa: F401  (fixture)

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


class RecordingLLM(FakeLLM):
    """Fake LLM whose calls are recorded like real ones (llm_calls rows) through the usage callback."""

    async def structured(self, role, schema, system, user):  # noqa: ANN001
        try:
            out = await super().structured(role, schema, system, user)
        except Exception:  # like the real callback: a failed call is recorded with no tokens
            await _record(role, failed=True)
            raise
        await _record(role)
        return out

    async def text(self, role, system, user):  # noqa: ANN001
        out = await super().text(role, system, user)
        await _record(role)
        return out


async def _record(role: str, failed: bool = False) -> None:
    from automind.application.usage import current_budget

    b = current_budget.get()
    await UsageRepo().record_llm(
        chat_id=b.chat_id,
        turn_id=b.turn_id,
        role=role,
        model="fake:model",
        input_tokens=0 if failed else 1000,
        output_tokens=0 if failed else 100,
        latency_ms=1,
        cost_eur=0.0 if failed else PRICES.llm_cost("fake:model", 1000, 100),
    )


@pytest.mark.usefixtures("fresh_variant")
async def test_turn_usage_matches_recorded_rows_including_agent(saver, chat_id):
    """A research turn: extractor, validator and reporter calls plus search calls all add up."""
    llm = llm_for_research().queue("interpreter", INTERPRET).queue("reporter", "Report.")
    rec = RecordingLLM(queues=llm.queues, responders=llm.responders)
    search = FixtureSearch("racer")
    calls = []

    class CountingSearch(FixtureSearch):
        async def search(self, query, *, market="ES", area=None):  # noqa: ANN001
            out = await super().search(query, market=market, area=area)
            from automind.application.usage import current_budget

            b = current_budget.get()
            await UsageRepo().record_search(
                chat_id=b.chat_id, turn_id=b.turn_id, kind="search", credits=1, cost_eur=self.eur_per_search
            )
            calls.append(query)
            return out

    ports = make_ports(llm=rec, search=CountingSearch("racer"))
    r = await ChatRunner(build_graph(saver, tools=[]), ports, budget_factory(), messages=MessageRepo()).run_turn(
        chat_id, "FixtureMake Racer for a race enthusiast"
    )
    totals = await UsageRepo().turn_totals(r.turn_id)
    assert r.usage["llm_calls"] == totals["llm_calls"] > 3
    assert r.usage["search_calls"] == totals["search_calls"] == len(calls) > 0
    assert r.usage["input_tokens"] == totals["input_tokens"]
    assert abs(r.usage["cost_eur"] - totals["cost_eur"]) < 1e-3
    del search


async def test_agent_steps_are_counted_by_the_model_callback():
    """create_agent runs several model steps; each one goes through the usage callback (FR-042)."""
    from langchain.agents import create_agent

    from automind.application.usage import Limits, TurnBudget, current_budget

    @tool
    def get_case(chat_id: str) -> str:
        """Case file."""
        return json.dumps({"persona": "BUYER"})

    class Repo:
        rows: list = []

        async def record_llm(self, **kw):
            self.rows.append(kw)

    repo = Repo()
    handler = UsageCallbackHandler("reporter", "m:fake", Prices({}, (1.0, 1.0), 0.0, {}), repo)  # type: ignore[arg-type]
    msgs = iter(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "get_case", "args": {"chat_id": "c"}, "id": "1"}],
                usage_metadata={"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
            ),
            AIMessage(content="Done.", usage_metadata={"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}),
        ]
    )

    class ToolModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kw):  # noqa: ANN001, ANN003
            return self

    model = ToolModel(messages=msgs, callbacks=[handler])
    budget = TurnBudget("c", "t", Prices({}, (1.0, 1.0), 0.0, {}), Limits())
    token = current_budget.set(budget)
    try:
        await create_agent(model, [get_case], system_prompt="x").ainvoke({"messages": [("user", "hi")]})
    finally:
        current_budget.reset(token)
    assert budget.calls == 2 == len(repo.rows)
    assert budget.input_tokens == 130 and budget.output_tokens == 25


async def test_cached_turn_counts_only_interpreter_and_answerer(saver, chat_id):
    await seed(load(GOLDEN / "g6_no_repeat.yaml"))
    rec = RecordingLLM()
    for t in (1, 2):
        for role, outs in json.loads((GOLDEN / "cassettes" / "g6_no_repeat" / f"turn{t}.json").read_text()).items():
            rec.queue(role, *outs)
    run = ChatRunner(
        build_graph(saver, tools=[]),
        make_ports(llm=rec, search=FixtureSearch("empty")),
        budget_factory(),
        messages=MessageRepo(),
    )
    await run.run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    r = await run.run_turn(chat_id, "Golf GTI Mk8 vs i30 N for a race enthusiast")
    totals = await UsageRepo().turn_totals(r.turn_id)
    assert r.usage["llm_calls"] == totals["llm_calls"] == 2 and totals["search_calls"] == 0
