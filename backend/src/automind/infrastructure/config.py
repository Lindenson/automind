"""YAML configuration loaders (config/*.yaml). The domain receives plain values, never files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from automind.application.ports import Reference
from automind.config import settings
from automind.domain import evidence
from automind.domain.criteria import CriteriaModel
from automind.domain.identity import Aliases


def config_dir() -> Path:
    return settings().config_dir


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    path = config_dir() / name
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def source_policy() -> evidence.SourcePolicy:
    d = load_yaml("sources.yaml")
    return evidence.SourcePolicy(
        manufacturer_markers=tuple(d["manufacturer_markers"]),
        instrumented=tuple(d["instrumented"]),
        encyclopedia=tuple(d["encyclopedia"]),
        spec_db=tuple(d["spec_db"]),
        denylist=tuple(d["denylist"]),
        non_manufacturer_hints=tuple(d.get("non_manufacturer_hints", ())),
    )


def fetch_policy() -> dict[str, Any]:
    return dict(load_yaml("sources.yaml")["fetch"])


def models() -> dict[str, str]:
    """Role -> "provider:model". Env MODEL_<ROLE> overrides the file (constitution VII)."""
    import os

    roles = {k: str(v) for k, v in load_yaml("models.yaml").items()}
    for role in list(roles):
        env = os.environ.get(f"MODEL_{role.upper()}")
        if env:
            roles[role] = env
    return roles


def prices() -> dict[str, Any]:
    return load_yaml("prices.yaml")


def rates() -> dict[str, Any]:
    return load_yaml("rates.yaml")


def aliases() -> dict[str, Any]:
    return load_yaml("aliases.yaml")


def generations() -> dict[str, list[tuple[str, int | None, int | None]]]:
    """Canonical "Make|Model" -> [(generation, from, to)] (config/generations.yaml)."""
    d = load_yaml("generations.yaml")
    return {
        k: [(str(g["generation"]), g.get("from"), g.get("to")) for g in v]
        for k, v in d.items()
        if k != "version" and isinstance(v, list)
    }


def questions() -> dict[str, str]:
    return {k: str(v) for k, v in load_yaml("questions.yaml").items() if k != "version"}


def reference(prompts: dict[str, str]) -> Reference:
    return Reference(
        aliases=Aliases.from_config(aliases()),
        generations=generations(),
        questions=questions(),
        prompts=prompts,
        queries={k: [str(q) for q in v] for k, v in load_yaml("queries.yaml").items() if k != "version"},
        criteria=CriteriaModel.from_config(load_yaml("criteria.yaml")),
        rates=rates(),
    )


def configure_domain() -> None:
    """Install config-driven policies into the pure domain (call once at startup and in tests)."""
    evidence.configure(source_policy())
