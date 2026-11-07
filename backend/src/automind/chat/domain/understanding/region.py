"""The region of Spain a person names, from config/regions.yaml words (spec 005)."""

from __future__ import annotations

from collections.abc import Mapping

from automind.chat.domain.case.enums import CLIMATES, Climate
from automind.shared.text.patterns import whole_word


def region_of(text: str | None, regions: Mapping[str, Mapping[str, object]]) -> tuple[str, Climate, str] | None:
    """(code, climate, the words) of the most specific region named in the text (the longest name wins); a region
    whose climate config/regions.yaml does not name is skipped."""
    if not text:
        return None
    low = text.lower()
    best: tuple[int, str, Climate, str] | None = None
    for code, info in regions.items():
        names = info.get("names")
        climate = CLIMATES.get(str(info.get("climate")))
        if climate is None or not isinstance(names, list):
            continue
        for name in names:
            n = str(name).lower()
            if whole_word(n).search(low) and (best is None or len(n) > best[0]):
                best = (len(n), code, climate, n)
    return (best[1], best[2], best[3]) if best else None
