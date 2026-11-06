"""Live re-run of chat 0d7fd924 (chat 4978a3de, 2026-11-04): Mazda CX-5 vs Honda CR-V, family, new 2025."""

from automind.chat.dialog.report_text import gap_text
from automind.chat.domain.assessment import ask_value
from automind.chat.domain.case.casefile import CaseFile
from automind.shared.research_order.plan import SourceHit, minimum_met


def _hit(domain: str, kind: str = "PUBLICATION") -> SourceHit:
    return SourceHit(domain=domain, source_type=kind, items=1)


def test_a_list_price_quoted_by_three_independent_sites_is_enough():
    """mazda.es was never read; carwow, autopista and autodescuento all said €35,990."""
    assert not minimum_met("price", [_hit("carwow.es"), _hit("autopista.es")])
    assert minimum_met("price", [_hit("carwow.es"), _hit("autopista.es"), _hit("autodescuento.com")])
    assert minimum_met("price", [_hit("mazda.es", "MANUFACTURER")])


def test_a_persona_from_the_users_own_words_is_not_asked_again():
    """ "для семейной покупки" gave BUYER (inferred); the report then asked "what matters most?" with that chip."""
    case = CaseFile(persona="BUYER", basis={"persona": "INFERRED"})
    case.profile.evidence["persona"] = "для семейной покупки"

    def outcome(c):
        return c.persona  # any other persona changes the outcome

    probes = {"persona": ["PERFORMANCE", "EXPERT"]}
    assert ask_value.questions(case, outcome, probes, kinds=("PERSONA",)) == []
    guessed = CaseFile(persona="BUYER", basis={"persona": "INFERRED"})
    assert ask_value.questions(guessed, outcome, probes, kinds=("PERSONA",)) == ["PERSONA"]


def test_gaps_speak_the_chats_language():
    assert gap_text("Mazda CX-5: price", "ru") == "Mazda CX-5: цена"
    assert gap_text("Mazda CX-5: reliability", "es") == "Mazda CX-5: fiabilidad"
    assert gap_text("Mazda CX-5: price", "en") == "Mazda CX-5: price"


def test_a_new_generation_without_reliability_history_still_gets_a_verdict():
    """The 2026 CX-5 cannot have reliability statistics: both cars were left unranked ("not enough data")."""
    from pathlib import Path

    import yaml

    from automind.chat.domain.assessment.criteria import CriteriaModel, score
    from automind.chat.domain.assessment.metrics import CarFacts, ReliabilitySummary, new_generation_since

    model = CriteriaModel.from_config(
        yaml.safe_load((Path(__file__).parents[2] / "config" / "criteria.yaml").read_text())
    )
    rel = ReliabilitySummary(recurring=0, isolated=7, high=0, minimum_met=True)
    w = {"practicality": 24.4, "reliability": 24.4, "ownership_cost": 20.3, "comfort": 16.3, "efficiency": 8.1,
         "safety": 6.5}  # fmt: skip
    base = {"powertrain": "ICE", "boot_l": 583, "seats": 5, "consumption": 7.0, "energy_eur_per_100km": 14.3}
    honda = CarFacts(
        "h",
        "Honda",
        **{**base, "boot_l": 579, "consumption": 6.7, "energy_eur_per_100km": 13.7},
        annual_cost_eur=2260,
        reliability=rel,
    )
    old = CarFacts("m", "Mazda", **base, annual_cost_eur=2366)
    assert not any(c.ranked for c in score([old, honda], w, model).cars)  # an unknown reliability: a real gap
    new = CarFacts("m", "Mazda", **base, annual_cost_eur=2366, new_generation_since=2026)
    got = score([new, honda], w, model)
    assert all(c.ranked for c in got.cars)
    assert "reliability" not in got.common  # left out, never guessed
    assert got.cars[0].parts["reliability"].unknowable
    assert new_generation_since(2026, 2026) == 2026 and new_generation_since(2017, 2026) is None


# ---- live chat 16c5fbc7 (re-run of 757cff3d): "Compare bmw 320d m line and vw golf variant 8.5 r" ----


def test_a_mild_hybrid_diesel_is_a_diesel():
    from types import SimpleNamespace

    from automind.shared.vehicle.identity import engine_fits

    hint = SimpleNamespace(fuel="diesel", displacement_l=2.0, power_kw=None)
    assert engine_fits(hint, None, 140, "mhev")  # "320d M Sport 2.0 Mild-Hybrid 190 CV"
    assert not engine_fits(hint, None, 140, "petrol")


def test_an_identified_car_is_not_asked_its_engine_and_used_is_never_cut():
    from automind.chat.application.services.interpretation import ask
    from automind.chat.domain.case.casefile import CaseCar, Choice, IdentifyOutcome

    bmw = CaseCar(key="car#1", request_text="bmw 320d m line", make="BMW", model="3 Series")
    bmw.identify = IdentifyOutcome(outcome="CHOICES", need="ENGINE",
                                   choices=[Choice(label=f"BMW 320d v{i}", make="BMW", model="3 Series")
                                            for i in range(5)])  # fmt: skip
    golf = CaseCar(key="car#2", request_text="vw golf variant 8.5 r", make="Volkswagen", model="Golf",
                   variant_id="v2", label="Golf Variant R 333 CV", resolution="PROPOSED")  # fmt: skip
    golf.identify = IdentifyOutcome(outcome="IDENTIFIED")
    case = CaseFile(cars=[bmw, golf])
    i18n = {"ENGINE": {"en": "Which engine of {car}: {options}?"}, "CONDITION": {"en": "New or used?"}}
    items = ask.intake_questions(["ENGINE", "CONDITION"], case, i18n, {}, ["car#1", "car#2"], "en")
    assert [(q["kind"], q["car"]) for q in items] == [("ENGINE", "car#1"), ("CONDITION", None)]
    labels = {"new": "New", "used": "Used", "yes": "Yes", "no": "No", "choose": "Choose", "remove": "Remove {car}",
              "automatic": "Automatic", "manual": "Manual"}  # fmt: skip
    chips = [c["label"] for c in ask.intake_quick_replies(items, case, labels)]
    assert "Used" in chips and "New" in chips and len(chips) <= ask.MAX_CHIPS


def test_a_320d_mild_hybrid_burns_diesel():
    from automind.shared.vehicle.identity import liquid_fuel

    assert liquid_fuel("3 Series 320d M Sport 8-speed automatic") == "diesel"
    assert liquid_fuel("X3 xDrive20d") == liquid_fuel("C 220 d") == liquid_fuel("e-Skyactiv D 2.2") == "diesel"
    assert liquid_fuel("Golf Variant R 2.0 TSI 4Motion DSG (333 CV)") == "petrol"
    assert liquid_fuel("Mazda CX-5 3rd gen") is None


def test_the_boot_volume_is_with_the_seats_up():
    from automind.shared.evidence.sense import boot_seats_up

    vw = "El Golf R Variant ofrece un grado de flexibilidad especialmente elevado: con un volumen máximo de maletero de 1.642 litros"  # noqa: E501
    assert not boot_seats_up("1642", vw).ok
    assert boot_seats_up("611", "Volumen mínimo con dos filas de asientos disponibles 611 litros").ok
    en = "Boot space 480 litres, 1,510 litres with the rear seats folded"
    assert boot_seats_up("480", en).ok and not boot_seats_up("1510", en).ok
    assert boot_seats_up("374", "| Maletero hasta las ventanas con asientos montados | 374 l |").ok
    assert boot_seats_up("621", "una capacidad de carga en el maletero de hasta 621 litros").ok


def test_thousands_follow_the_language():
    from automind.chat.dialog.report_text import fmt

    assert fmt(48500, "EUR", "en") == "€48,500"
    assert fmt(48500, "EUR", "es") == fmt(48500, "EUR", "ru") == "€48.500"
