"""A maker's engine code in the person's words — "C 200 d", "E 220 d", "GLC 300 e", "320d", "M340i", "220д" — read
as the engine family the ladder narrows by (owner 2026-11-28, chats fbdb4c8e / 6e032fe4: "C 200 d" and "320d" said
and asked again, because the code stayed a trim word). Pure."""

from __future__ import annotations

import re

_CYRILLIC = str.maketrans({"д": "d", "Д": "d", "і": "i", "е": "e", "Е": "e", "С": "C", "с": "c"})
# Mercedes-style class letters + number + suffix ("C 200 d", "GLC 300 e", "A 180"); BMW-style number + letter(s)
# ("320d", "118i", "M340i", "530e", "xDrive20d" is not a code of this kind)
_CODE = re.compile(
    r"^(?:(?P<m>M)?(?P<bnum>\d{3})\s?(?P<bsuf>d|i|e|li|xd)|(?P<cls>[A-Z]{1,3})\s?(?P<num>\d{3})\s?(?P<suf>d|e|h|i|de)?)$",
    re.IGNORECASE,
)


def engine_code(text: str | None) -> str | None:
    """The engine code `text` is ("C 200 d", "320d", "M340i"), written as the makers write it; None when it is not
    one code (a trim name, a sentence)."""
    m = _CODE.match(" ".join((text or "").translate(_CYRILLIC).split()))
    if m is None:
        return None
    if m.group("cls"):
        suffix = f" {m.group('suf').lower()}" if m.group("suf") else ""
        return f"{m.group('cls').upper()} {m.group('num')}{suffix}"
    return f"{'M' if m.group('m') else ''}{m.group('bnum')}{m.group('bsuf').lower()}"
