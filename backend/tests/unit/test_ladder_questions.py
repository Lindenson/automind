"""Spec 008 FR-004, FR-008, FR-013: a ladder question shows where the car stands, says what does not exist,
offers its options in the user's language, "choose for me" and "remove"."""

from automind.application import ask
from automind.domain.casefile import CaseCar, CaseFile, Choice, Constraints, IdentifyOutcome, LadderMemo
from automind.domain.identity import parse_engine
from automind.infrastructure.config import questions_i18n

Q = questions_i18n()
LABELS = {
    "new": "Nuevo",
    "used": "Usado",
    "yes": "Sí",
    "no": "No",
    "choose": "Elige tú",
    "remove": "Quitar {car}",
    "automatic": "Automático",
    "manual": "Manual",
}


def _audi() -> CaseCar:
    ch = [
        Choice(label=e, make="Audi", model="A4", level="ENGINE", engine=e, fuel=f, power_kw=kw)
        for e, f, kw in (("2.0 TFSI 150 CV", "petrol", 110), ("2.0 TDI 163 CV", "diesel", 120))
    ]
    return CaseCar(
        key="car#1",
        request_text="Audi A4 2.5",
        make="Audi",
        model="A4",
        condition="USED",
        year=2023,
        constraints=Constraints(engine_hint=parse_engine("2.5")),
        identify=IdentifyOutcome(outcome="CHOICES", need="ENGINE", level="ENGINE", choices=ch, missing=["2.5"]),
        ladder=LadderMemo(generation="B9"),
    )


def test_missing_and_status_line_in_the_question() -> None:
    case = CaseFile(cars=[_audi()])
    items = ask.intake_questions(["ENGINE"], case, Q, {}, ["car#1"], "es")
    text = items[0]["text"]
    first, second = text.split("\n")
    assert first == "Audi A4 · B9 (2023) · 2.5 · motor: ?"
    assert second == "El Audi A4 2023 no tiene la versión «2.5». Hay: 2.0 TFSI 150 CV, 2.0 TDI 163 CV. ¿Cuál?"


def test_ladder_chips_options_choose_and_remove() -> None:
    case = CaseFile(cars=[_audi()])
    items = ask.intake_questions(["ENGINE"], case, Q, {}, ["car#1"], "es")
    chips = [c["label"] for c in ask.intake_quick_replies(items, case, LABELS)]
    assert chips == ["2.0 TFSI 150 CV", "2.0 TDI 163 CV", "Elige tú", "Quitar Audi A4 2.5"]


def test_drive_options_in_the_users_language() -> None:
    car = _audi()
    car.identify = IdentifyOutcome(
        outcome="CHOICES",
        need="DRIVE",
        level="DRIVE",
        choices=[Choice(label="FWD", level="DRIVE", drive="FWD"), Choice(label="AWD", level="DRIVE", drive="AWD")],
    )
    car.constraints.engine_hint = parse_engine("2.0 TDI 150 CV")
    items = ask.intake_questions(["DRIVE"], CaseFile(cars=[car]), Q, {}, ["car#1"], "ru")
    assert [c["label"] for c in items[0]["choices"]] == ["передний привод", "полный привод"]
    assert items[0]["text"].startswith("Audi A4 · B9 (2023) · дизель 2.0 TDI 150 CV · привод: ?\n")
