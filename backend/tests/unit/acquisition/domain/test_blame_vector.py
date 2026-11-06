"""Spec 011 T061: vector blame, rules 1-5 of research R9 in order. Pure."""

from __future__ import annotations

import pytest

from automind.acquisition.domain.blame import LABEL_010, BlameCase, blame_vector, component_keys
from automind.acquisition.registry.domain.blame import blame

READER = {"producer": "reader", "producer_version": "km77@v1"}
LLM = {"producer": "extractor", "producer_version": "extract_specs@v3", "model": "google_genai:gemini-3.1-flash-lite"}


def case(**kw: object) -> BlameCase:
    base: dict[str, object] = {"attribute": "curb_mass", "claim_value": 1450.0, "truth": 1615.0,
                               "tolerance": ("rel", 0.03), "domain": "fastwrong.example", **READER}  # fmt: skip
    base.update(kw)
    return BlameCase(**base)  # type: ignore[arg-type]


def test_rule1_fusion_when_the_claim_was_right_but_the_selection_wrong() -> None:
    b = blame_vector(case(claim_value=1610.0, selected_value=1450.0))
    assert b.vector == {"fusion": 1.0} and b.rule == "fusion"


def test_rule2_relevance_by_verdict_and_by_sibling_gold() -> None:
    assert blame_vector(case(relevance="MULTI_VARIANT", excerpt="Peso 1450 kg")).vector == {"relevance": 1.0}
    b = blame_vector(case(siblings=(1452.0,), excerpt="Peso 1450 kg"))
    assert b.vector == {"relevance": 1.0} and b.rule == "relevance"
    # the right value is also on the page: half the relevance judge, half our reading
    split = blame_vector(case(siblings=(1452.0,), excerpt="Peso 1450 kg", page_text="520d ... peso 1.615 kg"))
    assert split.vector == {"relevance": 0.5, "parser": 0.5}


def test_rule3_units_and_sense() -> None:
    ps = blame_vector(case(attribute="max_power", claim_value=150.0, truth=110.3, tolerance=("rel", 0.02),
                           excerpt="Potencia máxima 150 CV"))  # fmt: skip
    assert ps.vector == {"units_sense": 1.0} and ps.rule_id == "units.ps_kw"
    hybrid = blame_vector(case(attribute="max_torque", claim_value=250.0, truth=400.0, hybrid=True,
                               excerpt="Par máximo del motor térmico 250 Nm"))  # fmt: skip
    assert hybrid.vector == {"units_sense": 1.0} and hybrid.rule_id == "sense.engine_vs_system_torque"
    assert LABEL_010["units_sense"] == "check"


def test_rule4_parser_or_extractor_by_producer() -> None:
    page = "Peso en orden de marcha 1.615 kg. Maletero 520 l."
    r = blame_vector(case(excerpt="Peso 1.615 kg", page_text=page))
    assert r.vector == {"parser": 1.0} and not r.disputed
    e = blame_vector(case(excerpt="Peso 1.615 kg", page_text=page, **LLM))
    assert e.vector == {"extractor": 1.0}
    keys = component_keys(case(**LLM), e)
    assert keys == {"extractor": "extract_specs@v3|google_genai:gemini-3.1-flash-lite"}
    assert component_keys(case(), r) == {"parser": "km77@v1"}


def test_rule5_source_and_disputed() -> None:
    s = blame_vector(case(excerpt="Peso 1450 kg", page_text="Peso 1450 kg"))
    assert s.vector == {"source": 1.0} and s.rule == "source"
    assert component_keys(case(), s) == {"source": "fastwrong.example"}
    # the truth is on the raw page but not in the excerpt: our reading is suspected, a judge must confirm
    d = blame_vector(case(excerpt="Peso 1450 kg", page_text="Ficha: Peso 1450 kg ... Masa total 1615 kg"))
    assert d.vector == {"parser": 1.0} and d.disputed
    m = blame_vector(case(excerpt="Peso 1615 kg", truth_confidence="MEDIUM"))
    assert m.disputed


@pytest.mark.parametrize(
    "c",
    [
        case(claim_value=1610.0, selected_value=1450.0),
        case(siblings=(1452.0,), excerpt="1450", page_text="1615"),
        case(excerpt="Peso 1450 kg"),
        case(excerpt="Peso 1615 kg"),
        case(attribute="max_power", claim_value=150.0, truth=110.3, excerpt="150 CV"),
    ],
)
def test_shares_sum_to_one(c: BlameCase) -> None:
    assert sum(blame_vector(c).vector.values()) == pytest.approx(1.0)


def test_010_blame_keeps_its_labels() -> None:
    assert blame("150 kW", "Leistung: 150 kW (204 PS)", "READER") == "parser"
    assert blame("150", "Potencia 150 kW", "LLM") == "extractor"
    assert blame("150", "Potencia 110 kW", "LLM") == "source"
    assert blame(None, "anything", "LLM") == "source"
    assert blame("1.598", "cilindrada 1598 cc", "LLM") == "extractor"
