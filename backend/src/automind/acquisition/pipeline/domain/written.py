"""Numbers and dates as a page writes them ("1.200,50", "2025-03-01"), read leniently: unreadable text is None."""

from __future__ import annotations

from datetime import date

from automind.shared.vehicle import units


def iso_date(raw: str | None) -> date | None:
    """An ISO date, None when absent or malformed."""
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def number(raw: str | None) -> float | None:
    """A number as a page writes it, None when there is none."""
    if not raw:
        return None
    try:
        return units.parse_number(raw)
    except Exception:  # noqa: BLE001 - any unreadable text is no number
        return None


def whole(raw: str | None) -> int | None:
    """The number as an integer (truncated), None when there is none."""
    n = number(raw)
    return int(n) if n is not None else None
