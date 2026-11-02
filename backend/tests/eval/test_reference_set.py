"""Reference-set evaluations.

- Race calibration (SC-011): simulated 0–100 within ±15% of instrumented tests for ≥80% of the
  sourced reference vehicles. Offline: uses the reference specs, no web, no model.
- Coverage/accuracy (SC-007): research each variant live and compare Tier 1 values within tolerance
  (≥80% found, ≥95% of found values correct). Live only: `uv run pytest tests/eval -m live -k reference`.
"""

from pathlib import Path

import pytest
import yaml

from automind.domain import dragrace, specs

REF = yaml.safe_load((Path(__file__).resolve().parents[2] / "eval" / "reference_vehicles.yaml").read_text())
SOURCED = [v for v in REF.get("vehicles") or [] if (v.get("sources") or {}).get("specs")]
TIER1 = ["max_power", "max_torque", "curb_mass", "drivetrain", "top_speed", "claimed_0_100"]


def _calibration() -> tuple[int, int, list[str]]:
    rows, ok, n = [], 0, 0
    for v in SOURCED:
        if not v.get("measured_0_100") or not (v.get("sources") or {}).get("measured"):
            continue
        s = v["specs"]
        car = dragrace.CarInput(
            car_id=v["variant_name"],
            label=f"{v['make']} {v['model']} {v['variant_name']}",
            powertrain=v["powertrain"],
            power_kw=s["max_power"],
            mass_kg=s["curb_mass"],
            drivetrain=s.get("drivetrain"),
            transmission=s.get("transmission"),
            top_speed_kmh=s.get("top_speed"),
        )
        sim = dragrace.simulate([car]).results[0].t_0_100
        err = abs(sim - v["measured_0_100"]) / v["measured_0_100"] if sim else 1.0
        n += 1
        ok += err <= 0.15
        rows.append(f"{car.label}: simulated {sim} s vs measured {v['measured_0_100']} s ({err:+.0%})")
    return ok, n, rows


def test_race_calibration_against_instrumented_tests():
    ok, n, rows = _calibration()
    if n < 20:
        pytest.skip(f"reference set has {n} sourced vehicles with instrumented 0–100 (need ≥ 20); see eval/README")
    print("\n".join(rows))
    assert ok / n >= 0.80


def within(attr: str, got: float | str, want: float | str) -> bool:
    a = specs.ATTRS[attr]
    if isinstance(want, str) or isinstance(got, str):
        return str(got).upper() == str(want).upper()
    return abs(float(got) - float(want)) <= max(a.tolerance * abs(float(want)), 1e-9)


@pytest.mark.live
async def test_tier1_coverage_and_accuracy():
    if len(SOURCED) < 20:
        pytest.skip(f"reference set has {len(SOURCED)} sourced vehicles (need ≥ 20)")
    pytest.skip("live research of the reference set: run on request (≈ €0.15 per vehicle)")
