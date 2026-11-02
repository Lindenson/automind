"""Model fallbacks when a provider quota is used up (Gemini free tier: requests per day per model)."""

import pytest

from automind.infrastructure import llm_gateway as g

DAILY = RuntimeError(
    "429 RESOURCE_EXHAUSTED ... GenerateRequestsPerDayPerProjectPerModel-FreeTier ... Please retry in 16h35m52.8s."
)
MINUTE = RuntimeError("429 RESOURCE_EXHAUSTED ... GenerateRequestsPerMinutePerProjectPerModel ... retry in 20s")


def test_quota_detection():
    assert abs(g.quota_exhausted(DAILY) - (16 * 3600 + 35 * 60 + 52.8)) < 1
    assert g.quota_exhausted(MINUTE) is None
    assert g.quota_exhausted(ValueError("bad schema")) is None


async def test_used_up_model_falls_back_and_is_skipped(monkeypatch):
    monkeypatch.setattr(g, "model_name", lambda role: "p:primary")
    monkeypatch.setattr(g.cfg, "model_fallbacks", lambda name: ["p:second"])
    monkeypatch.setattr(g, "_build", lambda role, name: name)
    g._EXHAUSTED.clear()
    calls = []

    async def call(model):
        calls.append(model)
        if model == "p:primary":
            raise DAILY
        return "ok"

    assert await g._with_fallbacks("x", call) == "ok"
    assert calls == ["p:primary", "p:second"]
    assert g.candidates("x") == ["p:second"]  # skipped until the quota resets
    g._EXHAUSTED.clear()


async def test_other_errors_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(g, "model_name", lambda role: "p:primary")
    monkeypatch.setattr(g.cfg, "model_fallbacks", lambda name: ["p:second"])
    monkeypatch.setattr(g, "_build", lambda role, name: name)

    async def call(model):
        raise ValueError("schema")

    with pytest.raises(ValueError):
        await g._with_fallbacks("x", call)


async def test_overloaded_model_falls_back_then_waits_and_gives_a_plain_error(monkeypatch):
    monkeypatch.setattr(g, "model_name", lambda role: "p:primary")
    monkeypatch.setattr(g.cfg, "model_fallbacks", lambda name: ["p:second"])
    monkeypatch.setattr(g, "_build", lambda role, name: name)
    real_sleep = g.asyncio.sleep

    async def no_wait(_s):
        await real_sleep(0)

    monkeypatch.setattr(g.asyncio, "sleep", no_wait)
    g._EXHAUSTED.clear()
    busy = RuntimeError("GoogleAPIError: 503 UNAVAILABLE. This model is currently experiencing high demand.")
    calls = []

    async def call(model):
        calls.append(model)
        if model == "p:primary":
            raise busy
        return "ok"

    assert await g._with_fallbacks("x", call) == "ok" and calls == ["p:primary", "p:second"]
    g._EXHAUSTED.clear()

    async def always_busy(model):
        raise busy

    with pytest.raises(g.ProviderUnavailable):
        await g._with_fallbacks("x", always_busy)
    from automind.orchestration.runner import user_error_text

    assert "overloaded" in user_error_text(g.ProviderUnavailable("503"))
    assert "503" not in user_error_text(busy)
    g._EXHAUSTED.clear()
