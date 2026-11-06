"""Delivery · bootstrap: assemble the configuration of the whole application once, at start (the composition of
reference data and domain policies from both areas). Every entry point — the web app, the MCP server, each CLI
command — and the test session call `configure_domain()` first.

It installs: the source policy and sense rules into the shared evidence domain, the chat's interpretation history
window, the factory that builds `Reference` (shared.infrastructure.config.runtime) and the engine's gated per-role
models (shared.infrastructure.llm.gateway). Code in the areas asks the runtime for a `Reference`; it never imports
this module.
"""

from __future__ import annotations

from automind.acquisition.infrastructure.config import plausibility_rules
from automind.chat.domain.assessment.criteria import CriteriaModel
from automind.shared import evidence
from automind.shared.contracts.config import Reference
from automind.shared.evidence import sense
from automind.shared.infrastructure.config import runtime
from automind.shared.infrastructure.config.loader import (
    aliases,
    favourite_queries,
    favourites,
    feasibility_rules,
    gearboxes,
    generations,
    load_yaml,
    open_queries,
    questions,
    questions_i18n,
    rates,
    search_config,
    source_policy,
)
from automind.shared.vehicle.identity import Aliases
from automind.shared.vehicle.makes import MakeRegistry


def configure_domain() -> None:
    """Install config-driven policies and the runtime factories (call once at startup and in tests)."""
    evidence.configure(source_policy())
    sense.configure(load_yaml("sense.yaml"))
    from automind.chat.application.services.interpretation.interpret import configure_history  # noqa: PLC0415

    win = search_config()["interpret"]
    configure_history(int(win["history_turns"]), int(win["history_chars"]))
    from automind.chat.application.services.report.compose import configure_severity  # noqa: PLC0415
    from automind.chat.domain.assessment.reliability import SeverityRules  # noqa: PLC0415

    configure_severity(SeverityRules.from_config(load_yaml("severity.yaml")))
    from automind.acquisition.infrastructure.overrides import role_model  # noqa: PLC0415
    from automind.shared.infrastructure.llm.gateway import set_role_model_source  # noqa: PLC0415

    runtime.install(reference)
    set_role_model_source(role_model)


def reference(prompts: dict[str, str]) -> Reference:
    from automind.acquisition.infrastructure.overrides import LayeredPrompts  # noqa: PLC0415

    return Reference(
        aliases=Aliases.from_config(aliases()),
        generations=generations(),
        questions=questions(),
        prompts=LayeredPrompts(prompts),  # spec 011 T104: gated prompt versions of the extractor roles
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
        outcome=load_yaml("outcome.yaml"),
        insight=load_yaml("insight.yaml"),
        registry=load_yaml("registry.yaml"),
    )
