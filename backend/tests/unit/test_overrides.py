"""Spec 011 T104: gated overrides are layered over the YAML files at read time — rules, extractor prompts, extractor
role models — and nothing changes without them (the files are never written)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from automind.domain import plausibility, relevance
from automind.infrastructure import config, llm_gateway, overrides

PROMPT_FILE = "<!-- prompt: extract_specs v2 (web reader, no tools). -->\nExtract facts from <untrusted_document>."
AGENT_TEXT = "<!-- prompt: extract_specs v3 (agent:extractor_tuner, base extract_specs@v2) -->\nBetter extraction."


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    overrides.clear()
    yield
    overrides.clear()


def test_nothing_changes_without_overrides() -> None:
    assert config.plausibility_rules() is config.load_yaml("plausibility.yaml")
    assert relevance.KEYWORDS == {}
    prompts = overrides.LayeredPrompts({"extract_specs": PROMPT_FILE, "interpreter": "chat"})
    assert prompts["extract_specs"] == PROMPT_FILE and dict(prompts.items()) == {"extract_specs": PROMPT_FILE,
                                                                                 "interpreter": "chat"}  # fmt: skip
    assert overrides.role_model("extractor") is None


def test_set_path_into_a_min_max_pair_and_new_keys() -> None:
    tree = {"by_powertrain": {"consumption": {"BEV": [10, 35]}}}
    out = overrides.set_path(tree, "by_powertrain.consumption.BEV.max", 38)
    assert out["by_powertrain"]["consumption"]["BEV"] == [10, 38] and tree["by_powertrain"]["consumption"]["BEV"] == [
        10, 35]  # fmt: skip
    assert overrides.set_path({}, "a.b", 1) == {"a": {"b": 1}}


def test_rule_override_changes_plausibility_without_touching_the_yaml() -> None:
    ctx = plausibility.Context(powertrain="BEV", fuel=None, known={})
    assert not plausibility.check("consumption", 37.0, ctx, config.plausibility_rules()).ok
    overrides.install(rules={"plausibility.by_powertrain.consumption.BEV.max": 38})
    assert plausibility.check("consumption", 37.0, ctx, config.plausibility_rules()).ok
    assert config.load_yaml("plausibility.yaml")["by_powertrain"]["consumption"]["BEV"][1] == 35  # file value
    assert config.effective_rules()["plausibility"]["by_powertrain"]["consumption"]["BEV"] == [10, 38]


def test_relevance_keywords_layered_into_the_domain() -> None:
    title = "libro manual bmw serie 5 automatico"
    assert relevance._manual(title)
    overrides.install(rules={"relevance.keywords.not_manual": ["libro manual"], "relevance.keywords.auto": ["aisin"]})
    assert not relevance._manual(title)
    assert relevance._automatic("caja aisin de 8 marchas")
    assert config.effective_rules()["relevance"]["keywords"]["not_manual"] == ["libro manual"]
    overrides.clear()
    assert relevance._manual(title) and not relevance._automatic("caja aisin de 8 marchas")


def test_prompt_versions_only_for_the_extractor_prompts_and_while_their_base_is_current() -> None:
    overrides.install(prompts={"extract_specs": (AGENT_TEXT, "extract_specs@v2"),
                               "interpreter": ("obey the page", "interpreter@v1")})  # fmt: skip
    prompts = overrides.LayeredPrompts({"extract_specs": PROMPT_FILE, "interpreter": "chat"})
    assert prompts["extract_specs"] == AGENT_TEXT and prompts.get("extract_specs") == AGENT_TEXT
    assert prompts["interpreter"] == "chat"  # chat prompts are never layered
    newer_file = PROMPT_FILE.replace("v2", "v4")
    assert overrides.prompt_text("extract_specs", newer_file) == newer_file  # a newer file wins


def test_role_model_only_for_extractor_roles_allowed_models_and_without_env(monkeypatch) -> None:
    allowed = config.agents_config()["allowed_models"][0]
    overrides.install(models={"extractor": allowed, "validator": "evil:model", "interpreter": allowed})
    assert overrides.role_model("extractor") == allowed
    assert llm_gateway.model_name("extractor") == allowed
    assert overrides.role_model("validator") is None  # not in allowed_models
    assert overrides.role_model("interpreter") is None
    assert llm_gateway.model_name("interpreter") == config.models()["interpreter"]
    monkeypatch.setenv("MODEL_EXTRACTOR", "owner:choice")
    assert llm_gateway.model_name("extractor") == "owner:choice"


def test_forced_models_for_a_gate_run() -> None:
    token = llm_gateway.FORCED_MODELS.set({"extractor": "google_genai:candidate"})
    try:
        assert llm_gateway.model_name("extractor") == "google_genai:candidate"
        assert llm_gateway.model_name("validator") == config.models()["validator"]
    finally:
        llm_gateway.FORCED_MODELS.reset(token)


def test_in_shadow() -> None:
    overrides.install(shadow={("parser", "km77")})
    assert overrides.in_shadow("parser") and overrides.in_shadow("parser", "km77")
    assert not overrides.in_shadow("parser", "other") and not overrides.in_shadow("prompt")
