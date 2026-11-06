"""Value retention and technology explainers (spec 004 FR-004, FR-005)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from automind.chat.application.services.report.blocks.engineering import tech_explainers
from automind.chat.application.services.report.facts.retention import retention_points
from automind.shared.infrastructure.config.loader import load_yaml

CURVE = load_yaml("feasibility.yaml")["depreciation"]
EXPLAINERS = load_yaml("tech_explainers.yaml")


def _car(retention=(), vehicle_class="compact", price=40000.0, transmission=None, powertrain="HEV", name="2.5 Hybrid"):
    sv = SimpleNamespace(available=True, value_num=price, value_text=None)
    tr = SimpleNamespace(available=True, value_num=None, value_text=transmission) if transmission else None
    values = {"official_price_es": sv, **({"transmission": tr} if tr else {})}
    v = SimpleNamespace(vehicle_class=vehicle_class, variant_name=name, powertrain=powertrain, transmission=None)
    return {"variant": v, "values": values, "retention": list(retention)}


def _point(years, share):
    r = SimpleNamespace(years=years, share=share, market="GB", excerpt=f"keeps {share * 100:.0f}% after {years} years")
    e = SimpleNamespace(source_name="Analyst", url="https://x.co.uk", source_type="PUBLICATION",
                        retrieved_at=datetime(2026, 11, 1, tzinfo=UTC))  # fmt: skip
    return r, e


def test_sourced_points_win_over_the_curve() -> None:
    pts = retention_points(_car([_point(3, 0.66), _point(3, 0.62), _point(3, 0.70)]), CURVE)
    three = next(p for p in pts if p["years"] == 3)
    assert three["basis"] == "SOURCED" and three["share"] == 0.66 and three["market"] == "GB"
    assert (three["low"], three["high"]) == (0.62, 0.70) and three["eur"] == 26400
    five = next(p for p in pts if p["years"] == 5)
    assert five["basis"] == "ASSUMPTION" and five["share"] == CURVE["compact"][5]


def test_explainer_follows_the_drivetrain() -> None:
    hybrid = tech_explainers(_car(transmission="e-CVT (power-split hybrid)"), EXPLAINERS)
    assert hybrid[0]["key"] == "power_split_hybrid" and all(h["key"] != "torque_converter" for h in hybrid)
    auto = tech_explainers(
        _car(transmission="automatic 6-speed", powertrain="ICE", name="2.0 e-Skyactiv G"), EXPLAINERS
    )
    assert {h["key"] for h in auto} & {"torque_converter", "mild_hybrid"}
