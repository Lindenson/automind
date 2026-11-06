"""Pytest plugin: dump every chat event a test publishes, normalised, one JSON file per test (spec 012 R11).

Loaded from outside the package (`-p behaviour_dump_plugin`, this directory on PYTHONPATH), so it works on any
commit, before and after a refactoring step. Active only when BEHAVIOUR_DUMP names an output directory.

What a test "did" = the ordered server→client events of its chats (`EventBus.publish`: progress, questions,
confirmation requests, blocks, replies, case-file changes). Ids, timestamps and durations are replaced by stable
placeholders, so two runs of the same behaviour give byte-identical files.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

# Where EventBus lives before and after the spec 012 tree move.
_EVENT_MODULES = ("automind.infrastructure.events", "automind.chat.infrastructure.events")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_HEX_ID = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{16}(?:[0-9a-f]{16})?\b")  # 16/32-hex ids, hashes
_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b")
_VOLATILE_KEYS = {"seq", "duration_ms", "elapsed_ms", "elapsed_s", "latency_ms", "created_at", "updated_at", "at",
                  "ts", "started_at", "finished_at", "eta_s"}  # fmt: skip

_events: list[dict[str, Any]] = []


def pytest_configure(config: pytest.Config) -> None:
    if not os.environ.get("BEHAVIOUR_DUMP"):
        return
    for name in _EVENT_MODULES:
        try:
            bus = importlib.import_module(name).EventBus
        except (ImportError, AttributeError):
            continue
        original = bus.publish

        async def publish(self: Any, chat_id: str, turn_id: str | None, type_: str, payload: dict[str, Any]) -> int:
            _events.append({"chat": chat_id, "turn": turn_id, "type": type_, "payload": payload})
            return await original(self, chat_id, turn_id, type_, payload)

        bus.publish = publish
        return
    raise pytest.UsageError(f"behaviour dump: EventBus not found in {_EVENT_MODULES}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):  # noqa: ANN201 - pytest hook wrapper
    _events.clear()
    yield
    out = os.environ.get("BEHAVIOUR_DUMP")
    if not out or not _events:
        return
    path = Path(out) / (re.sub(r"[^\w.-]+", "_", item.nodeid) + ".json")
    path.write_text(json.dumps(normalise(_events), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def normalise(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids: dict[str, str] = {}

    def ident(m: re.Match[str]) -> str:
        return ids.setdefault(m.group(0), f"<id{len(ids)}>")

    def walk(v: Any, key: str | None = None) -> Any:
        if key in _VOLATILE_KEYS:
            return "<v>"
        if isinstance(v, dict):
            return {walk(k): walk(x, k) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return _TS.sub("<ts>", _HEX_ID.sub(ident, _UUID.sub(ident, v)))
        if isinstance(v, float):
            return round(v, 6)
        return v

    return [walk(e) for e in events]
