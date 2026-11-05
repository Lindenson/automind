"""Mirror families: sites that copy each other count as one for agreement (spec 010 US6). Pure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def family_of(domain: str, families: Mapping[str, Sequence[str]]) -> str:
    d = domain.lower().removeprefix("www.")
    for name, members in families.items():
        if any(d == m or d.endswith("." + m) for m in members):
            return name
    return d
