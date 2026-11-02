"""A new car is matched to the current generation from config, not to a stale catalog row (RAV4 XA50 vs XA60)."""

from automind.application.resolve import _fits
from automind.domain.casefile import CaseCar
from automind.infrastructure import db
from automind.infrastructure.config import reference
from automind.orchestration.prompts import load_all


def test_new_rav4_is_not_the_previous_generation():
    ref = reference(load_all())
    xa50 = db.Variant(make="Toyota", model="RAV4", generation="XA50", variant_name="2.5 Hybrid", powertrain="HEV",
                      generation_years_from=2019, generation_years_to=None)  # fmt: skip
    new = CaseCar(key="car#1", request_text="new RAV4", make="Toyota", model="RAV4", condition="NEW")
    assert not _fits(xa50, new, None, 2026, ref)  # config: XA50 ended 2025
    assert _fits(xa50, new, None, 2026)  # without config the stale row still looks current
    used = CaseCar(key="car#1", request_text="RAV4 2021", make="Toyota", model="RAV4", condition="USED", year=2021)
    assert _fits(xa50, used, None, 2026, ref)
