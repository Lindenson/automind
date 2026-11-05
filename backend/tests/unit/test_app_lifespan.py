"""Spec 011 T055 (constitution XIII): the API process starts exactly one background task, retention. The metrics
snapshot, the registry review and the insight run are worker tasks (automind.acquisition.worker)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI

from automind.api import app as app_mod


class _Runner:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def resume_incomplete(self) -> list[str]:
        return []


class _Saver:
    async def adelete_thread(self, thread_id: str) -> None:
        return None


@asynccontextmanager
async def _checkpointer():
    yield _Saver()


async def _nothing(*a: Any, **k: Any) -> Any:
    return []


async def test_lifespan_creates_only_the_retention_task(monkeypatch: pytest.MonkeyPatch):
    started: list[str] = []
    real = asyncio.create_task

    def spy(coro: Any, **kw: Any) -> asyncio.Task:
        started.append(coro.__qualname__)
        return real(coro, **kw)

    async def retention_loop() -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(app_mod.db, "init_db", _nothing)
    monkeypatch.setattr(app_mod, "checkpointer", _checkpointer)
    monkeypatch.setattr(app_mod, "_mcp_tools", _nothing)
    monkeypatch.setattr(app_mod, "seed_if_empty", _nothing)
    monkeypatch.setattr(app_mod, "ChatRunner", _Runner)
    monkeypatch.setattr(app_mod.hub, "build_graph", lambda saver, tools: None)
    monkeypatch.setattr(app_mod, "live_ports", lambda bus, prompts: None)
    monkeypatch.setattr(app_mod, "load_prompts", lambda: {})
    monkeypatch.setattr(app_mod, "retention_loop", retention_loop)
    monkeypatch.setattr(app_mod.asyncio, "create_task", spy)
    async with app_mod.lifespan(FastAPI()):
        assert started == ["test_lifespan_creates_only_the_retention_task.<locals>.retention_loop"]


def test_the_api_no_longer_imports_the_moved_loops():
    from pathlib import Path

    text = Path(app_mod.__file__).read_text(encoding="utf-8")
    for name in ("registry_loop", "insight_loop", "metrics_loop"):
        assert name not in text
