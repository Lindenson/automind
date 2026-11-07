"""The stores' failure contract (application/ports.py): no driver exception leaves a store. A failed statement or
an unreachable database becomes `StoreUnavailable` with the cause chained; the ports' own errors pass through."""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from sqlalchemy.exc import SQLAlchemyError

from automind.chat.application.ports import StoreUnavailable

P = ParamSpec("P")
T = TypeVar("T")


def store_errors(fn: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, Coroutine[Any, Any, T]]:
    """Wrap a store method: SQLAlchemy errors and connection errors (OSError) become StoreUnavailable."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await fn(*args, **kwargs)
        except (SQLAlchemyError, OSError) as e:
            raise StoreUnavailable(f"{fn.__qualname__}: {type(e).__name__}") from e

    return wrapper
