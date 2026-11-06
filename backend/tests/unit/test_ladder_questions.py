"""Spec 008 FR-004, FR-008, FR-013: a ladder question shows where the car stands, says what does not exist,
offers its options in the user's language, "choose for me" and "remove"."""

from automind.chat.application.services.interpretation import ask
from automind.chat.domain.case.casefile import CaseCar, CaseFile, Choice, Constraints, IdentifyOutcome, LadderMemo
from automind.shared.infrastructure.config.loader import questions_i18n
from automind.shared.vehicle.identity import parse_engine

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
    assert first == "Audi A4 · B9 (2023) · motor: ?"  # "2.5" does not exist: not shown as settled
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


def test_two_cars_asked_together_keep_their_options_choose_and_remove() -> None:
    """Live chat 8c6a2a58: six A4 engines pushed the Octavia's "150 CV" and both "remove" chips past the cut."""
    audi = _audi()
    six = [
        Choice(label=f"{n} TFSI", make="Audi", model="A4", level="ENGINE", engine=f"{n} TFSI") for n in range(30, 36)
    ]
    audi.identify = IdentifyOutcome(outcome="CHOICES", need="ENGINE", level="ENGINE", choices=six)
    skoda = CaseCar(
        key="car#2", request_text="Skoda Octavia 2.0 diesel", make="Skoda", model="Octavia", condition="NEW",
        constraints=Constraints(engine_hint=parse_engine("2.0 diesel")),
        identify=IdentifyOutcome(outcome="CHOICES", need="POWER", level="POWER", choices=[
            Choice(label=f"2.0 TDI {cv} CV", make="Skoda", model="Octavia", level="POWER", power_kw=kw)
            for cv, kw in ((116, 85), (150, 110))]),
    )  # fmt: skip
    case = CaseFile(cars=[audi, skoda])
    items = ask.intake_questions(["ENGINE", "POWER"], case, Q, {}, ["car#1", "car#2"], "es")
    chips = [c["label"] for c in ask.intake_quick_replies(items, case, LABELS)]
    assert "2.0 TDI 116 CV" in chips and "2.0 TDI 150 CV" in chips
    assert "Elige tú" in chips
    assert sum(c.startswith("Quitar ") for c in chips) == 2
    assert len(chips) <= ask.MAX_CHIPS
