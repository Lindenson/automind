"""The failure contract of every store over the database: no driver exception leaves a store. A failed statement or
an unreachable database becomes the area's own "store unavailable" error with the cause chained; other errors (the
ports' own) pass through."""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

from sqlalchemy.exc import SQLAlchemyError

P = ParamSpec("P")
T = TypeVar("T")
StoreMethod = Callable[P, Coroutine[Any, Any, T]]


def translate_errors(error: type[Exception]) -> Callable[[StoreMethod[P, T]], StoreMethod[P, T]]:
    """A decorator for store methods: SQLAlchemy errors and connection errors (OSError) become `error`."""

    def decorate(fn: StoreMethod[P, T]) -> StoreMethod[P, T]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return await fn(*args, **kwargs)
            except (SQLAlchemyError, OSError) as e:
                raise error(f"{fn.__qualname__}: {type(e).__name__}") from e

        return wrapper

    return decorate
