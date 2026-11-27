"""Hypothesis strategies for the policy tests (spec 015 T204, T205): random valid situations over the facts the rules
read — cars with and without an identify outcome, every resolution and condition, budgets, candidates, intake
attempts, fingerprints equal to the case's or differing in one part, costs around the thresholds, every pass."""

from __future__ import annotations

from typing import Any, get_args

from hypothesis import strategies as st

from automind.chat.domain import intake
from automind.chat.domain.case import (
    MAX_CARS,
    Budget,
    CaseCar,
    CaseFile,
    Choice,
    Condition,
    Constraints,
    IdentifyKind,
    IdentifyOutcome,
    Intake,
    IntakeItem,
    Needs,
    Persona,
    Profile,
    QuestionKind,
    Resolution,
)
from automind.chat.domain.decision import CarState, RequestKind
from automind.chat.domain.fingerprint import fingerprint

from .builder import MAX_PASSES

MAKES = [None, "Kia", "Volkswagen"]
MODELS = [None, "Sorento", "Golf"]
ITEMS: list[str] = [*get_args(IntakeItem), "*"]


def _choice(i: int) -> Choice:
    return Choice(label=f"option {i}", variant_id=f"v{i}")


identify_outcomes = st.one_of(
    st.none(),
    st.builds(
        IdentifyOutcome,
        outcome=st.sampled_from(get_args(IdentifyKind)),
        need=st.one_of(st.none(), st.sampled_from(get_args(IntakeItem))),
        level=st.sampled_from([None, None, "FUEL", "ENGINE"]),
        choices=st.lists(st.integers(0, 3).map(_choice), max_size=2),
    ),
)


SETTLED_RESOLUTIONS: list[Resolution] = ["CONFIRMED", "CONFIRMED", "AUTO_OK", "PROPOSED", "UNRESOLVED"]
SETTLED_CONDITIONS: list[Condition] = ["NEW", "NEW", "USED", "UNKNOWN"]
identified = st.sampled_from([None, IdentifyOutcome(outcome="IDENTIFIED")])


@st.composite
def cars(draw: st.DrawFn, n: int, *, settled: bool) -> list[CaseCar]:
    """`n` cars; `settled`: make, model and version known (the late rules' ground), else anything goes."""
    return [
        CaseCar(
            key=f"car#{i + 1}",
            request_text=f"car {i + 1}",
            make=draw(st.sampled_from(MAKES[1:] if settled else MAKES)),
            model=draw(st.sampled_from(MODELS[1:] if settled else MODELS)),
            condition=draw(st.sampled_from(SETTLED_CONDITIONS if settled else get_args(Condition))),
            year=draw(st.sampled_from([None, 2019])),
            variant_id=f"v{i}" if settled else draw(st.sampled_from([None, f"v{i}", f"v{i}"])),
            resolution=draw(st.sampled_from(SETTLED_RESOLUTIONS if settled else get_args(Resolution))),
            identify=draw(identified if settled else identify_outcomes),
            constraints=Constraints(gearbox_hint=draw(st.sampled_from([None, "manual"]))),
            replaced=not settled and draw(st.booleans()) and draw(st.booleans()),
        )
        for i in range(n)
    ]


@st.composite
def cases(draw: st.DrawFn, *, settled: bool) -> CaseFile:
    n = draw(st.integers(1, MAX_CARS) if settled else st.integers(0, MAX_CARS + 1))
    case_cars = draw(cars(n, settled=settled))
    keys = [c.key for c in case_cars] + ["*"]
    attempts: dict[str, dict[str, int]] = draw(
        st.dictionaries(
            st.sampled_from(keys), st.dictionaries(st.sampled_from(ITEMS), st.integers(0, 3), max_size=3), max_size=3
        )  # fmt: skip
    )
    rare = [None, None, None, "Kia", "Volkswagen"]
    return CaseFile(
        cars=case_cars,
        persona=draw(st.sampled_from(["BUYER", "EXPERT"] if settled else get_args(Persona))),
        asked=draw(st.lists(st.sampled_from(get_args(QuestionKind)), max_size=4, unique=True)),
        budget=Budget(
            max_eur=draw(st.sampled_from([None, None, None, 25000] if settled else [None, 25000])),
            intent=draw(st.sampled_from(["UNKNOWN", "NEW", "ANY"])),
        ),  # fmt: skip
        candidates=draw(st.sampled_from([[], [], [{"make": "Kia", "model": "Sorento"}]])),
        wanted_make=draw(st.sampled_from(rare)),
        wanted_body=draw(st.sampled_from([None, "suv"])),
        profile=Profile(family=draw(st.sampled_from([None, "FAMILY", "SINGLE"]))),
        usage=draw(st.sampled_from([[], ["FAMILY"], ["CITY"]])),
        needs=Needs(passengers=draw(st.sampled_from([None, 2, 5]))),
        intake=Intake(
            attempts=attempts, card_confirmed=draw(st.booleans()), last_questions=draw(st.sampled_from([[], ["h1"]]))
        ),  # fmt: skip
    )


settled_states = st.builds(
    CarState,
    identity_known=st.just(True),
    in_catalog=st.booleans(),
    ambiguous=st.booleans(),
    plausible_generations=st.sampled_from([1, 1, 2]),
    data_fresh=st.booleans(),
    gearbox_mixed=st.sampled_from([False, False, True]),
)
car_states = st.builds(
    CarState,
    identity_known=st.booleans(),
    in_catalog=st.booleans(),
    ambiguous=st.booleans(),
    plausible_generations=st.integers(0, 3),
    data_fresh=st.booleans(),
    gearbox_mixed=st.booleans(),
)

limits = st.builds(
    intake.Limits,
    max_attempts_per_item=st.integers(1, 3),
    max_attempts_per_car=st.integers(1, 8),
    full_intake=st.booleans(),
)

# the thresholds of `builder.config()` (0.30, 1.00) and their neighbours, more often than any other value
boundaries = st.sampled_from([0.0, 0.29, 0.30, 0.30, 0.31, 0.99, 1.0, 1.0, 1.01])
# to the cent: the policy rounds the estimate half-up to the cent (spec 015 T211), the old chain compared the float
costs = st.one_of(st.none(), boundaries, boundaries, st.floats(0, 3, allow_nan=False).map(lambda x: round(x, 2)))


@st.composite
def fingerprints(draw: st.DrawFn, case: CaseFile) -> str | None:
    now = fingerprint(case)
    data, params = now.split(":")
    return draw(st.sampled_from([None, now, f"{data}:other", f"other:{params}", "legacy-without-colon"]))


@st.composite
def old_arguments(draw: st.DrawFn) -> dict[str, Any]:
    """The arguments of the old `decide(case, request, cars, **kw)`; every case car has a state or none (an
    unassessed car), and some states are for keys the case does not have."""
    settled = draw(st.sampled_from([True, True, False]))  # the late rules need settled cars to be reached
    case = draw(cases(settled=settled))
    keys = [c.key for c in case.cars]
    states = {k: draw(settled_states if settled else car_states) for k in keys if draw(st.integers(0, 6))}
    if draw(st.integers(0, 9)) == 0:
        states["car#9"] = draw(car_states)  # a state for a car the case does not have: ignored
    request: RequestKind = draw(st.sampled_from(get_args(RequestKind)))
    if settled and draw(st.booleans()):
        request = draw(st.sampled_from(["compare", "single", "follow_up_question", "weights_change", "correction",
                                        "research_more", "critique"]))  # fmt: skip
    return {
        "case": case,
        "request": request,
        "cars": states,
        "cost_estimate_eur": draw(costs),
        "last_fingerprint": draw(fingerprints(case)),
        "cost_approved": draw(st.booleans()),
        "research_declined": draw(st.booleans()),
        "case_changed": draw(st.booleans()),
        "feasibility_pending": draw(st.booleans()),
        "intake_limits": draw(limits),
        "hops": draw(st.sampled_from([0, 0, 0, 1, 3, MAX_PASSES - 1, MAX_PASSES])),
    }
