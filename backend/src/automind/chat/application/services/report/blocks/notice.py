"""Block notice: a short message shown with the report or the turn (info or warning)."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Level = Literal["info", "warning"]


class Notice(TypedDict):
    """A notice block as the chat receives it. `car_key`/`car_id` and `area` say what it is about, so a later step
    can drop a notice that another one explains better."""

    type: Literal["notice"]
    level: Level
    text: str
    car_key: NotRequired[str]
    car_id: NotRequired[str]
    area: NotRequired[str]


def notice(text: str, level: Level = "info", *, car_key: str | None = None, car_id: str | None = None,
           area: str | None = None) -> Notice:  # fmt: skip
    """A notice block; only the subjects given are set."""
    out: Notice = {"type": "notice", "level": level, "text": text}
    if car_key is not None:
        out["car_key"] = car_key
    if car_id is not None:
        out["car_id"] = car_id
    if area is not None:
        out["area"] = area
    return out
