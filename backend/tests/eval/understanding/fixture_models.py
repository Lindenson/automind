"""The format of `fixtures.yaml` (spec 013 T004): named case files and open bot questions with option ids, as the
understanding step sees them (understanding-spec §4 "Требование к Pending")."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from automind.chat.domain.case.enums import Condition, Resolution
from automind.shared.vehicle.engine import Fuel
from tests.eval.understanding.vocab import Lang, PendingKind

HERE = Path(__file__).parent
CarKey = str  # "car#N"


class Strict(BaseModel):
    """Every model of the set: unknown keys are errors (a typo in the YAML must not pass as "not checked")."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CarFixture(Strict):
    key: CarKey = Field(pattern=r"^car#\d+$")
    make: str | None
    model: str | None
    condition: Condition = "UNKNOWN"
    resolution: Resolution = "UNRESOLVED"
    label: str | None = None
    request_text: str | None = None  # the person's own words when they differ from make / model
    fuel: Fuel | None = None
    year: int | None = None
    replaced: bool = False


class CaseFixture(Strict):
    chat_language: Lang | None  # the chat's stable language; None = the first message of a chat
    report_shown: bool = False
    cars: list[CarFixture]

    def car_keys(self) -> set[CarKey]:
        return {c.key for c in self.cars}


class Option(Strict):
    id: str
    label: str


class PendingItem(Strict):
    car: CarKey | None
    topic: str = Field(pattern=r"^[A-Z_]+$")  # a QuestionKind, or CARD / PROPOSE / VERSION / CHOOSE / COST / LIMIT
    options: list[Option]


class PendingFixture(Strict):
    case: str  # the case file this question belongs to
    id: str
    kind: PendingKind
    question: str
    items: list[PendingItem] = Field(min_length=1)

    def option_ids(self) -> list[str]:
        return [o.id for item in self.items for o in item.options]

    def cars(self) -> set[CarKey]:
        return {item.car for item in self.items if item.car}


class Fixtures(Strict):
    cases: dict[str, CaseFixture]
    pendings: dict[str, PendingFixture]


def load_fixtures(path: Path = HERE / "fixtures.yaml") -> Fixtures:
    """The fixtures file, validated (raises pydantic.ValidationError on a malformed entry)."""
    return Fixtures.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
