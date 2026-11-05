"""Runtime overrides accepted through the gates, layered over the YAML files (spec 011 US5 T104; constitution XII).

Agents never write YAML: an accepted change activates a row in `rule_overrides`, `prompt_versions` or
`role_model_overrides`, and this module layers the active rows at read time (cached `REFRESH_S` seconds; the files
stay untouched):
- rules: `effective = yaml ⊕ active rule_overrides` for `plausibility.*`, `sense.*` and `relevance.keywords.*`
  (`.min`/`.max` address a `[min, max]` pair of plausibility.yaml);
- prompts: `extract_*`, `relevance`, `validator` return the active agent version's text while it derives from the
  prompt file's current version (a newer file wins); every other prompt is the file's text;
- models: `extractor`, `validator`, `relevance` use an active `role_model_overrides` row, only for a model in
  `config/agents.yaml: allowed_models` (an env `MODEL_<ROLE>` set by the owner still wins).
With no rows (the golden dialogues) every getter returns the file's value unchanged.
"""

from __future__ import annotations

import copy
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)
REFRESH_S = 60.0
MODEL_ROLES = ("extractor", "validator", "relevance")
RULE_SECTIONS = ("plausibility", "sense", "relevance")


def prompt_overridable(name: str) -> bool:
    return name.startswith("extract_") or name in ("relevance", "validator")


@dataclass
class _State:
    rules: dict[str, Any] = field(default_factory=dict)  # path -> value
    prompts: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # name -> (text, base_key)
    models: dict[str, str] = field(default_factory=dict)  # role -> model
    shadow: set[tuple[str, str]] = field(default_factory=set)  # (object_kind, object_key) in phase shadow
    loaded_at: float = float("-inf")


STATE = _State()


def clear() -> None:
    """Forget the cache (tests; the next `refresh()` reads the database)."""
    global STATE
    STATE = _State()
    _apply_domain()


def install(rules: Mapping[str, Any] | None = None, prompts: Mapping[str, tuple[str, str | None]] | None = None,
            models: Mapping[str, str] | None = None, shadow: set[tuple[str, str]] | None = None) -> None:  # fmt: skip
    """Set the cache directly (tests, and `refresh`)."""
    STATE.rules, STATE.prompts = dict(rules or {}), dict(prompts or {})
    STATE.models, STATE.shadow = dict(models or {}), set(shadow or ())
    STATE.loaded_at = time.monotonic()
    _apply_domain()


async def refresh(force: bool = False) -> None:
    """Reload the active rows (at most every REFRESH_S seconds unless forced); keep the cache on a database error."""
    if not force and time.monotonic() - STATE.loaded_at < REFRESH_S:
        return
    from sqlalchemy import text  # noqa: PLC0415

    from automind.infrastructure.db.session import sessionmaker  # noqa: PLC0415

    try:
        async with sessionmaker()() as s:
            rules = {str(p): v for p, v in (await s.execute(text(
                "SELECT path, value FROM rule_overrides WHERE status = 'active'"))).all()}  # fmt: skip
            prompts = {str(n): (str(t), b) for n, t, b in (await s.execute(text(
                "SELECT name, text, base_key FROM prompt_versions WHERE status = 'active' AND change_id IS NOT NULL"
            ))).all()}  # fmt: skip
            models = {str(r): str(m) for r, m in (await s.execute(text(
                "SELECT role, model FROM role_model_overrides WHERE active"))).all()}  # fmt: skip
            shadow = {(str(k), str(o)) for k, o in (await s.execute(text(
                "SELECT object_kind, object_key FROM acq_changes WHERE status = 'shadow' AND closed_at IS NULL"
            ))).all()}  # fmt: skip
    except Exception:  # noqa: BLE001 - the tables may not exist yet, or the database is restarting
        log.debug("overrides.refresh_failed", exc_info=True)
        STATE.loaded_at = time.monotonic()
        return
    install(rules, prompts, models, shadow)


def _apply_domain() -> None:
    """Relevance keywords and sense thresholds live in the pure domain: install their layered values."""
    from automind.domain import relevance, sense  # noqa: PLC0415

    prefix = "relevance.keywords."
    relevance.configure_keywords({p[len(prefix):]: v for p, v in STATE.rules.items()
                                  if p.startswith(prefix) and isinstance(v, list)})  # fmt: skip
    if any(p.startswith("sense.") for p in STATE.rules) or _SENSE_LAYERED[0]:
        from automind.infrastructure.config import load_yaml  # noqa: PLC0415

        sense.configure(layer("sense", load_yaml("sense.yaml")))
        _SENSE_LAYERED[0] = any(p.startswith("sense.") for p in STATE.rules)


_SENSE_LAYERED = [False]


# --- rules --------------------------------------------------------------------------------------------------------


def set_path(tree: Mapping[str, Any], path: str, value: Any) -> dict[str, Any]:
    """A copy of `tree` with `value` at the dotted `path` (without the section); `.min`/`.max` set one end of a
    `[min, max]` pair. Missing mappings are created."""
    out: dict[str, Any] = copy.deepcopy(dict(tree))
    parts = path.split(".")
    node: Any = out
    for i, part in enumerate(parts[:-1]):
        nxt = node.get(part) if isinstance(node, dict) else None
        if isinstance(nxt, list) and len(nxt) == 2 and parts[i + 1] in ("min", "max") and i + 2 == len(parts):
            nxt[0 if parts[i + 1] == "min" else 1] = value
            return out
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value
    return out


def layer(section: str, data: Mapping[str, Any], rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """`data` (one YAML file) with the active overrides of `section` applied; `data` itself when there are none."""
    rules = STATE.rules if rules is None else rules
    prefix = section + "."
    mine = sorted((p[len(prefix) :], v) for p, v in rules.items() if p.startswith(prefix))
    if not mine:
        return data  # type: ignore[return-value]
    out: dict[str, Any] = dict(data)
    for path, value in mine:
        out = set_path(out, path, value)
    return out


# --- prompts and models -------------------------------------------------------------------------------------------


def prompt_text(name: str, file_text: str) -> str:
    """The text to use for prompt `name`: the active agent version while it derives from the file's version."""
    got = STATE.prompts.get(name)
    if got is None or not prompt_overridable(name):
        return file_text
    from automind.acquisition.domain.versions import prompt_key  # noqa: PLC0415

    text, base = got
    return text if base == prompt_key(file_text, name) else file_text


class LayeredPrompts(dict[str, str]):
    """The prompt files by name, with the active agent versions of the overridable prompts layered on read."""

    def __getitem__(self, name: str) -> str:
        return prompt_text(name, super().__getitem__(name))

    def get(self, name: str, default: Any = None) -> Any:  # type: ignore[override]
        return self[name] if name in self else default  # noqa: SIM401 - get() would recurse

    def values(self) -> Any:  # type: ignore[override]
        return [self[k] for k in self]

    def items(self) -> Any:  # type: ignore[override]
        return [(k, self[k]) for k in self]


def role_model(role: str) -> str | None:
    """The gated model of an extractor role, or None (the file's model, or the owner's env override, applies)."""
    if role not in MODEL_ROLES or os.environ.get(f"MODEL_{role.upper()}"):
        return None
    model = STATE.models.get(role)
    if model is None:
        return None
    from automind.infrastructure.config import agents_config  # noqa: PLC0415

    try:
        allowed = set(agents_config().get("allowed_models") or [])
    except FileNotFoundError:
        return None
    return model if model in allowed else None


def in_shadow(kind: str, key: str | None = None) -> bool:
    """Whether a change of this object kind (and key) is in its shadow phase (cheap check before enqueueing)."""
    return any(k == kind and (key is None or o == key) for k, o in STATE.shadow)
