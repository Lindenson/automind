"""SC-003: for used cars with a stated year, the correct generation is resolved in ≥95% of cases.

Live only (real resolver model + search): `uv run pytest tests/eval -m live -s`.
"""

import re
from pathlib import Path

import pytest
import yaml

from automind.domain.casefile import CaseCar
from automind.domain.identity import generation_matches

CASES = yaml.safe_load((Path(__file__).parent / "used_resolution.yaml").read_text())["cases"]
TARGET = 0.95


def accepted(generation: str | None, accept: list[str]) -> bool:
    """Exact match, or the accepted code as a token at the start of a more specific answer ("B9" ⊂ "B9.5")."""
    g = (generation or "").strip().lower()
    for a in (x.lower() for x in accept):
        if a == g:
            return True
        if len(a) >= 2 and re.match(rf"{re.escape(a)}(?![0-9a-z])", g):
            return True
    return False


@pytest.mark.live
async def test_used_resolution_rate(migrated):
    from automind.application import resolve
    from automind.application.usage import current_budget
    from automind.infrastructure.adapters import live_ports
    from automind.infrastructure.db.repositories import EventRepo
    from automind.infrastructure.events import EventBus
    from automind.infrastructure.llm_gateway import new_budget
    from automind.orchestration.prompts import load_all

    ports = live_ports(EventBus(EventRepo()), load_all())
    token = current_budget.set(budget := new_budget(None, None))
    ok, rows = 0, []
    try:
        for c in CASES:
            car = CaseCar(
                key="car#1",
                request_text=f"used {c['make']} {c['model']} from {c['year']}",
                make=c["make"],
                model=c["model"],
                condition="USED",
                year=c["year"],
                age_years=2026 - c["year"],
            )
            try:
                v, _ = await resolve.resolve_with_llm(ports, car, 2026)
                gen, lo, hi = v.generation, v.generation_years_from, v.generation_years_to
            except resolve.GenerationMismatch as e:
                gen, lo, hi = f"mismatch: {e}", None, None
            good = accepted(gen, c["accept"]) and generation_matches(c["year"], lo, hi, tolerance=1)
            ok += good
            rows.append(f"{'✓' if good else '✗'} {c['make']} {c['model']} {c['year']}: {gen} ({lo}–{hi})")
    finally:
        current_budget.reset(token)
    rate = ok / len(CASES)
    print("\n" + "\n".join(rows) + f"\nrate {ok}/{len(CASES)} = {rate:.0%}, cost €{budget.cost_eur:.3f}")
    assert rate >= TARGET


def test_accepted_matching():
    assert accepted("B9.5 (8W facelift)", ["B9"]) and accepted("P2", ["P2"]) and accepted("Mk3 facelift", ["Mk3"])
    assert not accepted("B8", ["B9"]) and not accepted("Mk30", ["Mk3"]) and not accepted("IV", ["I"])
