"""The acquisition engine's public interface (spec 011, contracts/acquire.md).

The only engine module the chat (`automind.application`, `automind.orchestration`, `automind.domain`) may import
(FR-005, FR-006). The chat orders data here — "these kinds of data for this car, by this deadline" — and receives
values with confidence and sources, and for gaps the sources tried. Live calls run in the caller's process within
the caller's deadline and budget (research R5); background work runs in the worker. Everything else under
`automind.acquisition` is internal. Functions are added here only, task by task.
"""

from __future__ import annotations

from automind.acquisition.gold import repo as _gold

__all__: list[str] = ["record_challenge_gold"]


async def record_challenge_gold(
    variant_id: str, attribute: str, outcome: str, value: str | float | None, unit: str | None = None,
    challenge_id: str | None = None,
) -> bool:  # fmt: skip
    """A user challenge that ended CONFIRMED (the shown value) or CORRECTED (the newly selected value) becomes gold:
    origin `challenge`, rule `challenge_confirmed`/`challenge_corrected`, confidence MEDIUM (spec 011 FR-003).
    Returns whether a gold value was written."""
    return await _gold.record_challenge(variant_id, attribute, outcome, value, challenge_id, unit)
