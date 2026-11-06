"""Served-call identity (spec 011 T009): a caller can name the model and prompt version that answered its call."""

import asyncio
import contextlib
import uuid

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from pydantic import BaseModel

from automind.shared.infrastructure.llm import gateway as llm_gateway
from automind.shared.infrastructure.llm.usage_callback import UsageCallbackHandler, current_prompt
from automind.shared.metering.usage import Prices

PRICES = Prices(llm={}, default_llm=(0.0, 0.0), eur_per_credit=0.0, credits={})
PROMPT = "<!-- prompt: extract_specs v3 (web reader, no tools) -->\nExtract."


class Out(BaseModel):
    value: str


class _NoRepo:
    async def record_llm(self, **kwargs):  # noqa: ANN003
        return None


class _FakeModel:
    """Answers like `model.with_structured_output(schema, include_raw=True).ainvoke(messages)`, through the real
    usage callback, with a model chosen by the user text and after a delay (so concurrent calls interleave)."""

    def __init__(self, role: str, models: dict[str, str], delays: dict[str, float]) -> None:
        self.role, self.models, self.delays = role, models, delays

    def with_structured_output(self, schema, include_raw=True):  # noqa: ANN001
        return self

    async def ainvoke(self, messages):  # noqa: ANN001
        user = messages[-1][1]
        await asyncio.sleep(self.delays[user])
        cb = UsageCallbackHandler(self.role, self.models[user], PRICES, repo=_NoRepo())
        msg = AIMessage(content="{}", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        assert current_prompt.get() is not None
        await cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=uuid.uuid4())
        return {"parsed": Out(value=user), "parsing_error": None}


def fake_fallbacks(models: dict[str, str], delays: dict[str, float]):
    async def run(role, call):  # noqa: ANN001
        return await call(_FakeModel(role, models, delays))

    return run


async def test_concurrent_extractions_each_see_their_own_served_model(monkeypatch):
    models = {"A": "fake:model-a", "B": "fake:model-b"}
    monkeypatch.setattr(llm_gateway, "_with_fallbacks", fake_fallbacks(models, {"A": 0.05, "B": 0.0}))

    async def extraction(user: str):
        out = await llm_gateway.structured("extractor", Out, PROMPT, user)
        return out.value, llm_gateway.served("extractor")

    (ua, sa), (ub, sb) = await asyncio.gather(extraction("A"), extraction("B"))
    assert (ua, sa.model) == ("A", "fake:model-a")
    assert (ub, sb.model) == ("B", "fake:model-b")
    assert sa.prompt_key == sb.prompt_key == "extract_specs@v3"
    assert sa.role == "extractor"


async def test_each_call_resets_the_roles_served_identity(monkeypatch):
    models = {"A": "fake:model-a"}
    monkeypatch.setattr(llm_gateway, "_with_fallbacks", fake_fallbacks(models, {"A": 0.0}))

    async def failing(role, call):  # noqa: ANN001
        raise RuntimeError("provider down")

    async def scenario():
        await llm_gateway.structured("extractor", Out, PROMPT, "A")
        assert llm_gateway.served("extractor").model == "fake:model-a"
        monkeypatch.setattr(llm_gateway, "_with_fallbacks", failing)
        with contextlib.suppress(RuntimeError):
            await llm_gateway.structured("extractor", Out, PROMPT, "A")
        return llm_gateway.served("extractor")

    assert await asyncio.create_task(scenario()) is None


def test_prompt_without_header_is_legacy():
    call = llm_gateway.ServedCall("relevance", "fake:m", "relevance", None, "abc")
    assert call.prompt_key == "relevance@legacy"
