"""Owner 2026-11-28: the version line says a mild hybrid ("C 200 d … MHEV"), not only the engine."""

from types import SimpleNamespace

from automind.chat.application.services.report.blocks.car_view import engine_text


def _v(name: str, powertrain: str) -> object:
    return SimpleNamespace(variant_name=name, engine_cc=2000, power_kw=120, powertrain=powertrain)


def test_a_mild_hybrid_is_named_in_the_version_line() -> None:
    assert engine_text(_v("C 200 d automatic", "MHEV")) == "2.0 163 CV MHEV"  # type: ignore[arg-type]
    assert engine_text(_v("C 200 d automatic", "ICE")) == "2.0 163 CV"  # type: ignore[arg-type]
    assert engine_text(_v("320d MHEV automatic", "MHEV")).count("MHEV") <= 1  # type: ignore[arg-type]  # never twice
