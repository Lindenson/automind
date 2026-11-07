"""Chat · chat.domain.case: the case file — the structured, versioned understanding of the person and the task
(FR-002; R3), the aggregate root of the chat, and the only code that changes it.

Owns:
  `enums` — closed vocabularies (criteria keys, personas, conditions, usages, resolutions, question/intake kinds).
  `person` — profile, budget, running-cost limit, needs, rates, priorities, the person's own energy figures.
  `car` — a car in the case: request, constraints, options offered, identification outcome, ladder memo.
  `casefile` — `CaseFile`, the aggregate root, with the dialogue state it keeps (intake attempts, pending, shown).
  `delta` — `CaseDelta` (the interpreter's typed proposal) and `apply`, the only way a case changes (FR-003).
  `fit` — `Fit` and `Fit.from_case`: what the person needs, for ranking line-ups and candidates.
  `weights` — `set_weights`: criteria weights adjusted by hand (spec 007).
Flow: interpreter proposes a CaseDelta → delta.apply validates and merges it → a new CaseFile version is stored.
Depends on: shared.vehicle (engine), pydantic. Must not depend on: sqlalchemy, langgraph, fastapi, the application,
  the dialog, any infrastructure (import-linter domain-pure).
Public API: the names below (`from automind.chat.domain.case import CaseFile, CaseCar, apply`).
"""

from automind.chat.domain.case.car import (
    CaseCar,
    Choice,
    Constraints,
    IdentifyOutcome,
    LadderMemo,
)
from automind.chat.domain.case.casefile import (
    CaseFile,
    Intake,
    Pending,
    Prediction,
    RaceSettings,
    Shown,
)
from automind.chat.domain.case.delta import (
    CarContext,
    CarRef,
    CaseDelta,
    PersonaChange,
    PriorityChange,
    apply,
    apply_defaults,
)
from automind.chat.domain.case.enums import (
    BASIS_RANK,
    CLIMATES,
    CRITERION_KEYS,
    MAX_CARS,
    PROFILE_FIELDS,
    Body,
    BudgetIntent,
    Climate,
    Condition,
    CriterionKey,
    Depth,
    HomeCharging,
    IdentifyKind,
    IntakeItem,
    Persona,
    PersonaSource,
    ProfileBasis,
    QuestionKind,
    Resolution,
    Strength,
    Usage,
)
from automind.chat.domain.case.fit import (
    Fit,
)
from automind.chat.domain.case.person import (
    Budget,
    Needs,
    Priority,
    Profile,
    Rates,
    RunningLimit,
    StatedEnergy,
)
from automind.chat.domain.case.weights import (
    set_weights,
)

__all__ = [
    "BASIS_RANK",
    "Budget",
    "BudgetIntent",
    "CRITERION_KEYS",
    "CarContext",
    "CarRef",
    "CaseCar",
    "CaseDelta",
    "CaseFile",
    "Choice",
    "Body",
    "CLIMATES",
    "Climate",
    "Condition",
    "Constraints",
    "CriterionKey",
    "Depth",
    "HomeCharging",
    "IdentifyKind",
    "IdentifyOutcome",
    "Intake",
    "Fit",
    "IntakeItem",
    "LadderMemo",
    "MAX_CARS",
    "Needs",
    "PROFILE_FIELDS",
    "Pending",
    "Persona",
    "PersonaChange",
    "PersonaSource",
    "Prediction",
    "Priority",
    "PriorityChange",
    "Profile",
    "ProfileBasis",
    "QuestionKind",
    "RaceSettings",
    "Rates",
    "Resolution",
    "RunningLimit",
    "Shown",
    "StatedEnergy",
    "Strength",
    "Usage",
    "apply",
    "apply_defaults",
    "set_weights",
]
