"""Spec 009 US5 (FR-018…FR-020), chats 20b5b7f9 and 8c6a2a58: good pages rejected by our own relevance checks.

- "manuales del propietario" was read as a manual gearbox (FR-018: whole words only);
- a generation stored as the bare year "2024" rejected facelift pages of the same generation (FR-019);
- the brand's service and warranty pages were rejected as "not about this car" (FR-020).
"""

import pytest

from automind.acquisition.domain.relevance import (
    GenerationInfo,
    PageFacts,
    Target,
    judge,
    judge_brand,
    judge_service,
    resolve_generation,
)
from automind.shared.evidence import sense

MAKES = ["Audi", "BMW", "Kia", "Hyundai", "Toyota", "Mazda", "MG", "DS"]


def page(title: str, text: str = "", url: str = "https://example.es/x") -> PageFacts:
    return PageFacts(url=url, title=title, text=text)


# --- FR-018: gearbox and drive words are whole words ----------------------------------------------------------

SORENTO_AT = Target("Kia", "Sorento", "MQ4", 2020, None, "1.6 T-GDI PHEV 288 CV", transmission="automatic",
                    drive="AWD")  # fmt: skip
CX5_AT = Target("Mazda", "CX-5", "KF", 2017, 2025, "2.0 Skyactiv-G 165 CV", transmission="automatic", drive="FWD")
CX5_MT = Target("Mazda", "CX-5", "KF", 2017, 2025, "2.0 Skyactiv-G 165 CV", transmission="manual", drive="FWD")


@pytest.mark.parametrize(
    ("title", "url"),
    [
        ("Kia Sorento: manuales del propietario", "https://www.kia.com/es/manuales-del-propietario/sorento"),
        ("Manual de taller Kia Sorento MQ4", "https://example.es/kia-sorento-manual-de-taller"),
        ("Kia Sorento Handbuch und Bedienungsanleitung", "https://example.de/kia-sorento-handbuch"),
        ("Kia Sorento owner's manual", "https://example.com/kia-sorento-owners-manual"),
        ("Kia Sorento: manual del usuario", "https://example.es/x"),
    ],
)
def test_manual_inside_a_document_word_is_not_a_manual_gearbox(title: str, url: str) -> None:
    assert judge(page(title, "Kia Sorento MQ4", url), SORENTO_AT, []).verdict != "OTHER_VARIANT"


@pytest.mark.parametrize(
    "title",
    [
        "Mazda CX-5 2.0 165 CV cambio manual",
        "Mazda CX-5 2.0 165 CV manual 6 velocidades",
        "Mazda CX-5 2.0 165 CV 6-speed manual",
        "Mazda CX-5 2.0 165 CV Schaltgetriebe",
        "Mazda CX-5 2.0 165 CV 6MT",
    ],
)
def test_a_real_manual_gearbox_still_counts(title: str) -> None:
    assert judge(page(title, "Mazda CX-5 KF"), CX5_AT, []).verdict == "OTHER_VARIANT"


def test_automatic_words_are_whole_words() -> None:
    # "autos" / "autoescuela" are not an automatic gearbox; "automático" is
    assert judge(page("Mazda CX-5 2.0 165 CV: autos de ocasión", "Mazda CX-5 KF"), CX5_MT, []).verdict != (
        "OTHER_VARIANT"
    )
    assert judge(page("Mazda CX-5 2.0 165 CV automático", "Mazda CX-5 KF"), CX5_MT, []).verdict == "OTHER_VARIANT"


def test_drive_words_are_whole_words() -> None:
    awd = Target("Kia", "Sorento", "MQ4", 2020, None, "1.6 T-GDI PHEV 288 CV", drive="FWD")
    # "integrales" (servicios integrales) is not "tracción integral"
    assert judge(page("Kia Sorento servicios integrales", "Kia Sorento MQ4"), awd, []).verdict != "OTHER_VARIANT"
    assert judge(page("Kia Sorento tracción integral", "Kia Sorento MQ4"), awd, []).verdict == "OTHER_VARIANT"


def test_sense_gearbox_family_reads_whole_words() -> None:
    assert sense.gearbox_family("ver manuales del propietario") is None
    assert sense.gearbox_family("manual de taller") is None
    assert sense.gearbox_family("cambio manual de 6 velocidades") == "manual"
    assert sense.gearbox_family("6-speed manual") == "manual"
    assert sense.gearbox_family("Schaltgetriebe 6 Gänge") == "manual"
    assert not sense.gearbox_conflict("automatic", "consulte los manuales")


# --- FR-019: a bare-year generation maps to the generation containing it -----------------------------------------

SORENTO_GENS = [GenerationInfo("XM", 2009, 2014), GenerationInfo("UM", 2015, 2020), GenerationInfo("MQ4", 2020, None)]
SORENTO_2024 = Target("Kia", "Sorento", "2024", 2024, None, "1.6 T-GDI PHEV 288 CV", fuel="petrol", body="SUV")


def test_bare_year_generation_is_mapped_to_its_code_and_years() -> None:
    tgt, gens = resolve_generation(SORENTO_2024, [*SORENTO_GENS, GenerationInfo("2024", 2024, None)])
    assert (tgt.generation, tgt.years_from, tgt.years_to) == ("MQ4", 2020, None)
    assert [g.code for g in gens] == ["XM", "UM", "MQ4"]


def test_pages_of_the_same_generation_incl_facelift_are_relevant() -> None:
    gens = [*SORENTO_GENS, GenerationInfo("2024", 2024, None)]
    pre = page("Kia Sorento PHEV 2022: prueba", "El Sorento híbrido enchufable 1.6 T-GDI de 265 CV")
    assert judge(pre, SORENTO_2024, gens).verdict == "RELEVANT"
    lift = page("Kia Sorento 2024 facelift: más tecnología", "El Sorento MQ4 renovado")
    assert judge(lift, SORENTO_2024, gens).verdict == "RELEVANT"
    old = page("Kia Sorento 2017 2.2 CRDi: prueba", "El Sorento UM")
    r = judge(old, SORENTO_2024, gens)
    assert r.verdict == "OTHER_VARIANT" and r.other is not None and r.other.startswith("UM")


def test_bare_year_without_a_known_generation_does_not_reject_nearby_years() -> None:
    r = judge(page("Kia Sorento PHEV 2022: prueba", "Sorento"), SORENTO_2024, [])
    assert r.verdict != "OTHER_VARIANT"


def test_the_sorento_generations_are_known_to_the_config() -> None:
    from automind.shared.infrastructure.config.loader import generations  # noqa: PLC0415

    gens = [GenerationInfo(g, a, b) for g, a, b in generations()["Kia|Sorento"]]
    tgt, _ = resolve_generation(SORENTO_2024, gens)
    assert (tgt.generation, tgt.years_from) == ("MQ4", 2020)


def test_a_real_generation_code_is_kept() -> None:
    tgt = Target("Kia", "Sorento", "MQ4", 2020, None, "x")
    assert resolve_generation(tgt, SORENTO_GENS)[0] == tgt


# --- FR-020: brand-wide service and warranty pages ------------------------------------------------------------

SORENTO = Target("Kia", "Sorento", "MQ4", 2020, None, "1.6 T-GDI PHEV 288 CV", fuel="petrol", body="SUV")


def test_brand_wide_maintenance_page_naming_the_make_is_relevant() -> None:
    p = page("Plan de mantenimiento Kia: revisiones oficiales", "Kia te ofrece revisiones cada 15.000 km o 1 año.",
             "https://www.kia.com/es/servicios/mantenimiento/")  # fmt: skip
    assert judge_service(p, SORENTO, SORENTO_GENS, MAKES).verdict == "RELEVANT"
    w = page(
        "Garantía Kia 7 años", "Todos los Kia nuevos tienen 7 años de garantía.", "https://www.kia.com/es/garantia/"
    )
    assert judge_service(w, SORENTO, SORENTO_GENS, MAKES).verdict == "RELEVANT"


def test_service_page_of_another_make_is_not_relevant() -> None:
    p = page("Plan de mantenimiento Hyundai", "Hyundai: revisiones cada 15.000 km. Compárelo con Kia.",
             "https://www.hyundai.com/es/mantenimiento")  # fmt: skip
    assert judge_service(p, SORENTO, SORENTO_GENS, MAKES).verdict != "RELEVANT"
    assert judge_brand(p, "Kia", MAKES).verdict == "NOT_ABOUT_CAR"


def test_service_page_of_another_generation_is_still_rejected() -> None:
    p = page("Kia Sorento UM 2017 mantenimiento", "Revisiones del Sorento UM", "https://example.es/sorento-um")
    assert judge_service(p, SORENTO, SORENTO_GENS, MAKES).verdict == "OTHER_VARIANT"


def test_non_service_brand_page_is_not_accepted_by_the_service_rule() -> None:
    p = page("Kia: noticias de la marca", "Kia presenta su nueva gama.", "https://www.kia.com/es/noticias/")
    assert judge_service(p, SORENTO, SORENTO_GENS, MAKES).verdict != "RELEVANT"
