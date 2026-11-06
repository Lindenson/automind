"""Configuration levers (spec 010 FR-009, research R15). Pure.

The analyst may propose a configuration fix only for a declared file and key path that exists in the loaded YAML;
anything else becomes a code fix. The system never applies either.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _matches(pattern: str, key: str) -> bool:
    p, k = pattern.split("."), key.split(".")
    return len(p) == len(k) and all(a in ("*", b) for a, b in zip(p, k, strict=True))


def _exists(doc: Any, key: str) -> bool:
    cur = doc
    for part in key.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return False
        cur = cur[part]
    return True


def check_fix(
    component: str, fix: Mapping[str, Any], levers: Mapping[str, Any], docs: Mapping[str, Any]
) -> dict[str, Any]:
    out = dict(fix)
    if out.get("kind") != "config":
        return out
    f, k = str(out.get("config_file") or ""), str(out.get("config_key") or "")
    allowed = any(lv.get("file") == f and _matches(str(lv.get("key")), k) for lv in levers.get(component) or [])
    if allowed and _exists(docs.get(f), k):
        return out
    note = f"(proposed as configuration `{f}: {k}`, which is not a declared lever or does not exist)"
    out.update({"kind": "code", "direction": " ".join(x for x in (str(out.get("direction") or ""), note) if x)})
    return out
