"""A new car is matched to the current generation from config, not to a stale catalog row (RAV4 XA50 vs XA60)."""

from automind.chat.application.services.identification.resolve import _fits
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.case.casefile import CaseCar
from automind.delivery.bootstrap import reference
from automind.shared.infrastructure import db


def test_new_rav4_is_not_the_previous_generation():
    ref = reference(load_all())
    xa50 = db.Variant(make="Toyota", model="RAV4", generation="XA50", variant_name="2.5 Hybrid", powertrain="HEV",
                      generation_years_from=2019, generation_years_to=None)  # fmt: skip
    new = CaseCar(key="car#1", request_text="new RAV4", make="Toyota", model="RAV4", condition="NEW")
    assert not _fits(xa50, new, None, 2026, ref)  # config: XA50 ended 2025
    assert _fits(xa50, new, None, 2026)  # without config the stale row still looks current
    used = CaseCar(key="car#1", request_text="RAV4 2021", make="Toyota", model="RAV4", condition="USED", year=2021)
    assert _fits(xa50, used, None, 2026, ref)


def test_current_generation_for_new_cars():
    from automind.chat.application.services.identification.resolve import current_generation

    ref = reference(load_all())
    new = CaseCar(key="car#1", request_text="new RAV4", make="Toyota", model="RAV4", condition="NEW")
    assert current_generation(ref, new, 2026) == ("XA60", 2026)
    assert current_generation(ref, new, 2024) == ("XA50", 2019)
    used = new.model_copy(update={"condition": "USED"})
    assert current_generation(ref, used, 2026) is None


def test_catalog_row_without_generation_is_not_reused_when_config_knows_generations():
    ref = reference(load_all())
    bare = db.Variant(make="Mazda", model="CX-5", generation=None, variant_name="Homura (2025+)", powertrain="ICE")
    new = CaseCar(key="car#1", request_text="new CX-5", make="Mazda", model="CX-5", condition="NEW")
    assert not _fits(bare, new, None, 2026, ref)


async def test_revalidate_resets_a_new_car_on_a_finished_generation(monkeypatch):
    from automind.chat.application.services.identification import resolve

    ref = reference(load_all())
    xa50 = db.Variant(id="v-xa50", make="Toyota", model="RAV4", generation="XA50", variant_name="2.5 Hybrid",
                      powertrain="HEV", generation_years_from=2019)  # fmt: skip

    async def fake_get(vid):
        return xa50

    monkeypatch.setattr(resolve, "get_variant", fake_get)
    car = CaseCar(key="car#1", request_text="new RAV4", make="Toyota", model="RAV4", condition="NEW",
                  variant_id="v-xa50", label="Toyota RAV4 XA50", resolution="CONFIRMED")  # fmt: skip
    reason = await resolve.revalidate(car, ref, 2026)
    assert reason and "XA50" in reason and car.variant_id is None and car.resolution == "UNRESOLVED"
    used = CaseCar(key="car#2", request_text="RAV4 2021", make="Toyota", model="RAV4", condition="USED", year=2021,
                   variant_id="v-xa50", resolution="CONFIRMED")  # fmt: skip
    assert await resolve.revalidate(used, ref, 2026) is None and used.variant_id == "v-xa50"


def test_same_model_spec_005() -> None:
    from automind.chat.application.services.identification.resolve import same_model

    assert (
        same_model("Seal U", "Seal U DM-i") and same_model("Seal U DM-i", "Seal U") and same_model("SEAL U", "Seal U")
    )
    assert (
        not same_model("Seal U", "Dolphin") and not same_model("Seal U", "Seal") and not same_model("Atto 3", "Atto 2")
    )
    assert same_model("Ateca", "Ateca") and same_model(None, "Dolphin")
