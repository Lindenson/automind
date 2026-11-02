"""Relevance gate before extraction (spec 003 FR-013, SC-004; research R7). Pure and deterministic."""

from hypothesis import given
from hypothesis import strategies as st

from automind.domain.relevance import GenerationInfo, PageFacts, Target, judge, power_ps_of

PRADO = [GenerationInfo("J120", 2002, 2009), GenerationInfo("J150", 2009, 2023), GenerationInfo("J250", 2024, None)]
GOLF = [GenerationInfo("Mk7", 2012, 2016), GenerationInfo("Mk7.5", 2017, 2019), GenerationInfo("Mk8", 2020, 2023)]
BMW3 = [GenerationInfo("F30", 2012, 2018), GenerationInfo("G20", 2019, None)]
BMW5 = [GenerationInfo("F10", 2010, 2016), GenerationInfo("G30", 2017, 2023), GenerationInfo("G60", 2023, None)]
ECLASS = [GenerationInfo("W212", 2009, 2016), GenerationInfo("W213", 2016, 2023), GenerationInfo("W214", 2023, None)]


def t(make, model, gen, frm, to, variant, fuel="diesel", body="SEDAN"):
    return Target(make=make, model=model, generation=gen, years_from=frm, years_to=to, variant=variant, fuel=fuel,
                  body=body)  # fmt: skip


P150 = t("Toyota", "Land Cruiser Prado", "J150", 2009, 2023, "2.8 D-4D 177 CV", body="SUV")
G30 = t("BMW", "5 Series", "G30", 2017, 2023, "520d 190 CV")


def page(title, text="", url="https://example.com/x"):
    return PageFacts(url=url, title=title, text=text)


def test_other_generation_in_title_is_rejected():
    r = judge(page("Toyota Land Cruiser Prado J250 2.8 D-4D: prueba", "El nuevo Prado J250 2024 ..."), P150, PRADO)
    assert r.verdict == "OTHER_VARIANT" and r.other == "J250 (2024–)"
    assert "J250" in r.reason


def test_target_generation_mentioned_is_relevant():
    r = judge(page("Toyota Land Cruiser Prado J150 (2009-2023) ficha técnica", "177 CV, 2.8 D-4D ..."), P150, PRADO)
    assert r.verdict == "RELEVANT"


def test_golf_mk8_for_mk7_target():
    mk7 = t("Volkswagen", "Golf", "Mk7", 2012, 2016, "GTI 2.0 TSI 220 CV", fuel="petrol", body="HATCHBACK")
    r = judge(page("Volkswagen Golf GTI Mk8 review", "The eighth-generation Golf GTI, Mk8, 245 PS"), mk7, GOLF)
    assert r.verdict == "OTHER_VARIANT" and r.other.startswith("Mk8")


def test_bmw_g20_for_f30_and_w213_for_w212():
    f30 = t("BMW", "3 Series", "F30", 2012, 2018, "320d 190 CV")
    assert judge(page("BMW 320d G20 (2019) test", "The new G20 3 Series"), f30, BMW3).verdict == "OTHER_VARIANT"
    w212 = t("Mercedes-Benz", "E-Class", "W212", 2009, 2016, "E 220 CDI 170 CV")
    r = judge(page("Mercedes E 220 d W213 Fahrbericht", "Die neue E-Klasse W213"), w212, ECLASS)
    assert r.verdict == "OTHER_VARIANT" and r.other.startswith("W213")


def test_g60_page_for_g30_target():
    r = judge(page("BMW 520d G60 2024 prueba", "La nueva generación G60"), G30, BMW5)
    assert r.verdict == "OTHER_VARIANT" and r.other.startswith("G60")


def test_years_outside_the_generation_point_to_a_sibling():
    r = judge(page("BMW Serie 5 520d 2012 datos técnicos", "", "https://www.km77.com/coches/bmw/serie-5/2012/x"),
              G30, BMW5)  # fmt: skip
    assert r.verdict == "OTHER_VARIANT" and r.other.startswith("F10")


def test_facelift_year_inside_the_generation_is_relevant():
    url = "https://www.km77.com/coches/bmw/serie-5/2021/berlina/estandar/520d-berlina/datos"
    assert (
        judge(page("BMW Serie 5 520d berlina (2021) | Datos técnicos", "190 CV", url), G30, BMW5).verdict == "RELEVANT"
    )


def test_engine_power_mismatch_is_another_variant():
    r = judge(page("BMW Serie 5 G30 530d 265 CV datos técnicos", "265 CV, 620 Nm"), G30, BMW5)
    assert r.verdict == "OTHER_VARIANT" and "265" in r.reason


def test_power_within_five_percent_is_the_same_engine():
    assert judge(page("BMW 520d G30 140 kW (190 PS) technical data"), G30, BMW5).verdict == "RELEVANT"


def test_body_mismatch_is_another_variant():
    url = "https://www.km77.com/coches/bmw/serie-5/2017/touring/estandar/520d-touring/datos"
    r = judge(page("BMW Serie 5 520d Touring (2017) | Datos técnicos", "190 CV", url), G30, BMW5)
    assert r.verdict == "OTHER_VARIANT" and "touring" in r.reason.lower()


def test_multi_engine_page():
    text = "BMW 5 Series G30 engines: 520d 190 PS | 530d 265 PS | 540i 340 PS | 520i 184 PS"
    assert judge(page("BMW 5 Series G30 (2017-2023) engines and specs", text), G30, BMW5).verdict == "MULTI_VARIANT"


def test_page_not_about_the_car():
    r = judge(page("Best pizza in Madrid", "Our pizzeria offers ..."), G30, BMW5)
    assert r.verdict == "NOT_ABOUT_CAR"


def test_no_signals_is_uncertain():
    assert judge(page("BMW 520d review", "A comfortable diesel saloon."), G30, BMW5).verdict == "UNCERTAIN"


def test_power_parsing():
    assert power_ps_of("520d 190 CV") == 190
    assert power_ps_of("2.0 TDI 150 PS") == 150
    assert abs(power_ps_of("140 kW") - 190.3) < 0.5
    assert power_ps_of("Long Range AWD") is None


@given(st.text(max_size=300), st.text(max_size=80))
def test_deterministic(text, title):
    a = judge(page(title, text), G30, BMW5)
    b = judge(page(title, text), G30, BMW5)
    assert a == b


def test_model_names_with_dashes_and_digits_are_recognised():
    cx5 = t("Mazda", "CX-5", "KF", 2017, 2025, "2.5 Skyactiv-G 194 CV", fuel="petrol", body="SUV")
    gens = [GenerationInfo("KE", 2012, 2016), GenerationInfo("KF", 2017, 2025)]
    assert judge(page("CX-5 2.5 194 CV ficha técnica (2019)", "Datos del CX-5"), cx5, gens).verdict != "NOT_ABOUT_CAR"
