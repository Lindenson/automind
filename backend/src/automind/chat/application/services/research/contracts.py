"""Contracts of the research service: what it tells the chat while it works (status lines, the car × area grid),
and the two words it needs in the person's language."""

from __future__ import annotations

from typing import Any, Protocol


class ResearchEvents(Protocol):
    """The turn's event stream (the dialog's TurnContext): status lines and grid progress."""

    async def emit(self, type_: str, payload: dict[str, Any]) -> int: ...

    async def status(self, stage: str, text: str, **extra: Any) -> None: ...


class ResearchWording(Protocol):
    """A phrase in the person's language and the name of a research area (the dialog's wording)."""

    def t(self, key: str, lang: str | None, **params: object) -> str: ...

    def area_label(self, area: str, lang: str | None) -> str: ...
