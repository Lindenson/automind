"""The acquisition engine's configuration files (read, never written; constitution XII): acquisition.yaml,
gold_datasets.yaml, physics.yaml, agents.yaml, and the source fetch policy of sources.yaml."""

from __future__ import annotations

from typing import Any

from automind.acquisition.snapshots.codec import RetentionCfg
from automind.shared.infrastructure.config.loader import load_yaml


def fetch_policy() -> dict[str, Any]:
    return dict(load_yaml("sources.yaml")["fetch"])


def acquisition_config() -> dict[str, Any]:
    """config/acquisition.yaml: snapshots, worker, schedule, prefetch, drift, replay."""
    return load_yaml("acquisition.yaml")


def gold_datasets_config() -> dict[str, Any]:
    """config/gold_datasets.yaml: dataset endpoints, attribute map, conversions, tolerances, strip words."""
    return load_yaml("gold_datasets.yaml")


def physics_config() -> dict[str, Any]:
    """config/physics.yaml: physical consistency checks (research R8)."""
    return load_yaml("physics.yaml")


def agents_config() -> dict[str, Any]:
    """config/agents.yaml: agent budgets, gates, levers, allowed models (research R13, R14)."""
    return load_yaml("agents.yaml")


def snapshot_retention() -> RetentionCfg:
    """Typed snapshot retention settings (research R1)."""
    return RetentionCfg.from_config(acquisition_config()["snapshots"])


def gold_tolerances() -> dict[str, tuple[str, float]]:
    """attribute -> ("abs" | "rel", tolerance) for gold comparison."""
    out: dict[str, tuple[str, float]] = {}
    for attr, t in (gold_datasets_config().get("tolerances") or {}).items():
        kind = "abs" if "abs" in t else "rel"
        out[str(attr)] = (kind, float(t[kind]))
    return out


def plausibility_rules() -> dict[str, Any]:
    """config/plausibility.yaml with the active gated `rule_overrides` layered on top (spec 011 T104)."""
    from automind.acquisition.infrastructure import overrides  # noqa: PLC0415

    return overrides.layer("plausibility", load_yaml("plausibility.yaml"))


def effective_rules() -> dict[str, Any]:
    """The rule files agents may tune, as in force now (YAML ⊕ active overrides): plausibility, sense, relevance."""
    from automind.acquisition.domain import relevance  # noqa: PLC0415
    from automind.acquisition.infrastructure import overrides  # noqa: PLC0415

    keywords = {k: list(v) for k, v in relevance.KEYWORDS.items()}
    return {"plausibility": plausibility_rules(), "sense": overrides.layer("sense", load_yaml("sense.yaml")),
            "relevance": {"keywords": {k: keywords.get(k, []) for k in relevance.KEYWORD_LISTS}}}  # fmt: skip
