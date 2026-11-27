"""A value read from a store once per run of the graph (spec 014 D3): the first `get` loads it, later ones reuse it.

`TurnContext` is built for every `ainvoke` (a new turn, a resume, a restart), so a `Cached` never outlives the run
that read it. The owner of the value keeps it current (`put` after its own write) or drops it (`forget`) when the
store may have moved on; parallel nodes of one run (research jobs) share one load.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class Cached(Generic[T]):
    """One value of the run, loaded by `load` on first use. Errors of `load` propagate and nothing is cached."""

    def __init__(self, load: Callable[[], Awaitable[T]]) -> None:
        self._load = load
        self._lock = asyncio.Lock()
        self._box: tuple[T] | None = None  # a box: the value itself may be None

    async def get(self) -> T:
        """The value: loaded once (concurrent callers wait for the same load), then kept until `forget`."""
        async with self._lock:
            if self._box is None:
                self._box = (await self._load(),)
            return self._box[0]

    def put(self, value: T) -> None:
        """Replace the value with what the owner just wrote (no load)."""
        self._box = (value,)

    def forget(self) -> None:
        """Drop the value: the next `get` loads it again."""
        self._box = None
