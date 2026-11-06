"""The region of Spain a person names, from config/regions.yaml words (spec 005)."""

from __future__ import annotations

from automind.shared.text.patterns import whole_word


def region_of(text: str | None, regions: dict[str, dict[str, object]]) -> tuple[str, str, str] | None:
    """(code, climate, the words) of the most specific region named in the text (the longest name wins)."""
    if not text:
        return None
    low = text.lower()
    best: tuple[int, str, str, str] | None = None
    for code, info in regions.items():
        for name in info.get("names") or []:  # type: ignore[attr-defined]
            n = str(name).lower()
            if whole_word(n).search(low) and (best is None or len(n) > best[0]):
                best = (len(n), code, str(info.get("climate")), n)
    return (best[1], best[2], best[3]) if best else None
