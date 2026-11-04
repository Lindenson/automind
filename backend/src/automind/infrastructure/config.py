"""YAML configuration loaders (config/*.yaml). The domain receives plain values, never files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from automind.application.makes import MakeRegistry
from automind.application.ports import Reference
from automind.config import settings
from automind.domain import evidence, sense
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


def _official_domains(d: dict[str, Any]) -> tuple[str, ...]:
    sites = {str(x).split("/")[0].removeprefix("www.").lower() for x in (d.get("manufacturer_sites") or {}).values()}
    return tuple(sorted(sites | {str(x).lower() for x in d.get("official_domains") or ()}))


def source_policy() -> evidence.SourcePolicy:
    d = load_yaml("sources.yaml")
    return evidence.SourcePolicy(
        manufacturer_markers=tuple(d["manufacturer_markers"]),
        instrumented=tuple(d["instrumented"]),
        encyclopedia=tuple(d["encyclopedia"]),
        spec_db=tuple(d["spec_db"]),
        denylist=tuple(d["denylist"]),
        non_manufacturer_hints=tuple(d.get("non_manufacturer_hints", ())),
        official_domains=_official_domains(d),
        typed_domains=tuple(
            (str(f["domain"]).lower(), str(f["source_type"]))
            for f in d.get("favourites") or []
            if f.get("source_type") in SOURCE_TYPES
        ),
    )


def fetch_policy() -> dict[str, Any]:
    return dict(load_yaml("sources.yaml")["fetch"])


def models() -> dict[str, str]:
    """Role -> "provider:model". Env MODEL_<ROLE> overrides the file (constitution VII)."""
    import os

    roles = {k: str(v) for k, v in load_yaml("models.yaml").items() if k not in ("options", "fallbacks", "version")}
    for role in list(roles):
        env = os.environ.get(f"MODEL_{role.upper()}")
        if env:
            roles[role] = env
    return roles


def model_options(name: str) -> dict[str, Any]:
    """Provider options for one model ("provider:model"), from models.yaml `options`."""
    return dict((load_yaml("models.yaml").get("options") or {}).get(name) or {})


def model_fallbacks(name: str) -> list[str]:
    """Models to use when `name` has used up its quota (models.yaml `fallbacks`)."""
    return [str(x) for x in (load_yaml("models.yaml").get("fallbacks") or {}).get(name) or []]


def prices() -> dict[str, Any]:
    return load_yaml("prices.yaml")


def rates() -> dict[str, Any]:
    """config/rates.yaml with the energy model (config/energy.yaml, spec 006) under `energy`."""
    return {**load_yaml("rates.yaml"), "energy": load_yaml("energy.yaml")}


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


def gearboxes() -> dict[str, list[str]]:
    """ "Make|Model|generation" (generation lower-case) -> gearboxes sold new in Spain (generations.yaml)."""
    d = load_yaml("generations.yaml")
    return {
        f"{k}|{str(g['generation']).lower()}": [str(x) for x in g["transmissions"]]
        for k, v in d.items()
        if k != "version" and isinstance(v, list)
        for g in v
        if g.get("transmissions")
    }


def questions() -> dict[str, str]:
    """English question texts by kind (v1 shape, used by the 002–004 code paths)."""
    out = {}
    for k, v in questions_i18n().items():
        out[k] = str(v.get("en", "")) if isinstance(v, dict) else str(v)
    return out


def questions_i18n() -> dict[str, Any]:
    """config/questions.yaml v2: {kind: {en, ru, es, bare?, rephrase?}} (spec 005 R9)."""
    return {k: v for k, v in load_yaml("questions.yaml").items() if k != "version"}


def _query_areas() -> dict[str, Any]:
    return {k: v for k, v in load_yaml("queries.yaml").items() if k != "version"}


def open_queries() -> dict[str, list[str]]:
    return {k: [str(q) for q in (v.get("open") or [])] for k, v in _query_areas().items()}


def favourite_queries() -> dict[str, str]:
    out = {k: str(v["favourite"]) for k, v in _query_areas().items() if v.get("favourite")}
    for k, v in _query_areas().items():  # per-market wording: favourite_by_market: {DE: '…'}
        for market, tpl in (v.get("favourite_by_market") or {}).items():
            out[f"{k}@{str(market).upper()}"] = str(tpl)
    return out


PROVIDERS = ("serper", "serpapi", "tavily")
MARKETS = ("ES", "EN", "DE", "ANY")
SOURCE_TYPES = ("MANUFACTURER", "INSTRUMENTED_TEST", "SPEC_DATABASE", "PUBLICATION", "ENCYCLOPEDIA")


def search_config() -> dict[str, Any]:
    """config/search.yaml with the SEARCH_PROVIDER env override; validated at start."""
    d = dict(load_yaml("search.yaml"))
    if settings().search_provider:
        d["provider"] = settings().search_provider
    for p in [d.get("provider"), *(d.get("fallback") or [])]:
        if p not in PROVIDERS:
            raise ValueError(f"config/search.yaml: unknown search provider {p!r} (known: {', '.join(PROVIDERS)})")
    return d


def favourites() -> list[dict[str, Any]]:
    """Favourite sources (config/sources.yaml); a favourite on the deny-list is a configuration error."""
    d = load_yaml("sources.yaml")
    deny = [str(x).lower() for x in d.get("denylist", [])]
    out = []
    for f in d.get("favourites") or []:
        dom = str(f["domain"]).lower()
        if any(x in dom for x in deny):
            raise ValueError(f"config/sources.yaml: favourite {dom} is on the deny-list")
        if f.get("source_type") not in SOURCE_TYPES:
            raise ValueError(f"config/sources.yaml: favourite {dom}: unknown source_type {f.get('source_type')!r}")
        bad = [m for m in f.get("markets", []) if m not in MARKETS]
        if bad:
            raise ValueError(f"config/sources.yaml: favourite {dom}: unknown markets {bad}")
        out.append(dict(f, domain=dom))
    return out


def plausibility_rules() -> dict[str, Any]:
    return load_yaml("plausibility.yaml")


def feasibility_rules() -> dict[str, Any]:
    return load_yaml("feasibility.yaml")


def reference(prompts: dict[str, str]) -> Reference:
    return Reference(
        aliases=Aliases.from_config(aliases()),
        generations=generations(),
        questions=questions(),
        prompts=prompts,
        queries=open_queries(),
        favourite_queries=favourite_queries(),
        search=search_config(),
        favourites=favourites(),
        manufacturer_sites=dict(load_yaml("sources.yaml").get("manufacturer_sites") or {}),
        plausibility=plausibility_rules(),
        feasibility=feasibility_rules(),
        criteria=CriteriaModel.from_config(load_yaml("criteria.yaml"), load_yaml("profile_rules.yaml")),
        rates=rates(),
        insights=load_yaml("insights.yaml"),
        layouts=load_yaml("report_layouts.yaml"),
        explainers=load_yaml("tech_explainers.yaml"),
        questions_i18n=questions_i18n(),
        makes=MakeRegistry.from_config(load_yaml("makes.yaml")),
        regions=dict(load_yaml("regions.yaml").get("regions") or {}),
        profile_defaults=load_yaml("profile_defaults.yaml"),
        gearboxes=gearboxes(),
    )


def configure_domain() -> None:
    """Install config-driven policies into the pure domain (call once at startup and in tests)."""
    evidence.configure(source_policy())
    sense.configure(load_yaml("sense.yaml"))
    from automind.application.interpret import configure_history  # noqa: PLC0415

    win = search_config().get("interpret") or {}
    configure_history(int(win.get("history_turns", 16)), int(win.get("history_chars", 800)))
