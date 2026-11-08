"""Declarative parser specification (spec 011 US4, contracts/parser-spec.md, research R10). Pure.

The only form in which a site reader can change (constitution XII): which pages a reader applies to, labels mapped to
attributes, CSS selectors, JSON-LD paths and unit hints. The interpreter that executes it is fixed code
(`parsing/readers/interpreter.py`); a spec only fills its parameters — no expression language, no code (FR-020).
`check()` lists every problem of a proposal before any gate; an empty list means valid.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from automind.acquisition.parsing.readers import spec_check

SKIP_VALUES = ["-", "No disponible"]
Layout = Literal["table", "divrow", "dl", "css"]


class FieldRule(BaseModel):
    """One attribute a reader takes from the page: from a label, a CSS selector or a JSON-LD path, with unit hints."""

    model_config = ConfigDict(extra="forbid")

    attribute: str
    label: str | None = None  # label text, matched after norm_label()
    prefix: bool = False  # the label matches the start of the cell text
    css: str | None = None  # selector of the value element (layout "css" only)
    jsonld: str | None = None  # dotted path into the page's JSON-LD (e.g. "vehicleEngine.enginePower.value")
    unit: str | None = None  # force this unit
    prefer_unit: str | None = None  # when a cell lists several units, take the number before this one
    text: bool = False  # keep the cell as text (drivetrain, gearbox)

    @model_validator(mode="after")
    def _one_source(self) -> FieldRule:
        if sum(x is not None for x in (self.label, self.css, self.jsonld)) != 1:
            raise ValueError(f"{self.attribute}: exactly one of label / css / jsonld")
        return self

    def hints(self) -> dict[str, Any]:
        """The unit hints in the mapping form `normalise.cell_value.value_and_unit` reads."""
        return {"unit": self.unit, "prefer_unit": self.prefer_unit, "text": self.text}


class ParserSpec(BaseModel):
    """A site reader as data: the domains and pages it reads, the layout of label/value pairs, and its fields."""

    model_config = ConfigDict(extra="forbid")

    reader: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    version: int = Field(ge=1)
    domains: list[str] = Field(min_length=1, max_length=5)
    url_patterns: list[str] = []
    page_type: Literal["spec_table"] = "spec_table"
    layout: Layout
    row_css: str | None = None
    label_css: str | None = None
    value_css: str | None = None
    fields: list[FieldRule] = Field(min_length=1, max_length=60)
    min_rows: int = Field(default=3, ge=1, le=60)
    skip_values: list[str] = Field(default_factory=lambda: list(SKIP_VALUES))
    notes: str = Field(default="", max_length=500)

    @field_validator("domains")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [d.strip().lower() for d in v]

    @property
    def key(self) -> str:
        """`km77@v1` (research R2)."""
        return f"{self.reader}@v{self.version}"

    def check(self, sources: Mapping[str, Mapping[str, Any]] | None = None, denylist: Iterable[str] = ()) -> list[str]:
        """Every semantic problem of this spec (`spec_check.problems`); [] = valid."""
        return spec_check.problems(self, sources, tuple(denylist))


def parse(data: ParserSpec | Mapping[str, Any] | str | bytes) -> tuple[ParserSpec | None, list[str]]:
    """(spec, []) or (None, schema errors) from a spec, its dict or its JSON text."""
    if isinstance(data, ParserSpec):
        return data, []
    try:
        raw = json.loads(data) if isinstance(data, (str, bytes)) else dict(data)
    except (ValueError, TypeError) as e:
        return None, [f"not JSON: {e}"]
    try:
        return ParserSpec.model_validate(raw), []
    except ValidationError as e:
        return None, _pydantic_errors(e)


def check(
    data: ParserSpec | Mapping[str, Any] | str | bytes,
    *,
    sources: Mapping[str, Mapping[str, Any]] | None = None,
    denylist: Iterable[str] = (),
) -> list[str]:
    """Every problem of a proposed spec (schema, attributes, units, selectors, regexes, domains, size); [] = valid.
    `sources` maps registry domains to `{access, frozen, status}`; None skips the registry check (fixtures)."""
    spec, errs = parse(data)
    if spec is None:
        return errs
    return spec.check(sources, denylist)


def _pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = "extra key not allowed" if err["type"] == "extra_forbidden" else err["msg"]
        out.append(f"{loc or 'spec'}: {msg}")
    return out
