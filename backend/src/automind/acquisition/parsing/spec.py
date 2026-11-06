"""Declarative parser specification (spec 011 US4, contracts/parser-spec.md, research R10). Pure.

The only form in which a site reader can change (constitution XII): which pages a reader applies to, labels mapped to
attributes, CSS selectors, JSON-LD paths and unit hints. The interpreter that executes it is fixed code
(`parsing/interpreter.py`); a spec only fills its parameters — no expression language, no code (FR-020).
`check()` lists every problem of a proposal before any gate; an empty list means valid.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from automind.shared.vehicle import specs, units

MAX_BYTES = 20 * 1024
MAX_PATTERN = 200
SKIP_VALUES = ["-", "No disponible"]
Layout = Literal["table", "divrow", "dl", "css"]
_JSONLD = re.compile(r"[A-Za-z@_][\w@]*(\.[A-Za-z@_0-9][\w@]*)*")


def norm_label(label: str) -> str:
    """Labels are matched after lowercasing, ":" removal and whitespace collapsing (as the v1 readers did)."""
    return " ".join(label.lower().replace(":", " ").split())


class FieldRule(BaseModel):
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
        """The unit hints in the mapping form `interpreter.value_and_unit` reads."""
        return {"unit": self.unit, "prefer_unit": self.prefer_unit, "text": self.text}


class ParserSpec(BaseModel):
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
        return _semantic(self, sources, tuple(denylist))


def _attr_unit_ok(attribute: str, unit: str) -> bool:
    a = specs.ATTRS.get(attribute)
    if a is None or a.kind == "text":
        return a is not None
    if a.convert is None:
        return True
    try:
        a.convert(1.0, unit)
    except (units.UnitError, ValueError):
        return False
    return True


def _selector_problem(sel: str) -> str | None:
    from selectolax.lexbor import LexborHTMLParser  # noqa: PLC0415 - the parser the interpreter uses

    try:
        LexborHTMLParser("<p></p>").css(sel)
    except Exception as e:  # noqa: BLE001 - selectolax raises plain exceptions on bad selectors
        return f"bad CSS selector {sel!r}: {e}"
    return None


def _children(op: Any, av: Any) -> list[Any]:
    """The sub-patterns of one node of the stdlib's regex parse tree."""
    from re import _constants as c  # noqa: PLC0415

    if op == c.SUBPATTERN:
        return [av[-1]]
    if op == c.BRANCH:
        return list(av[1])
    if op in (c.ASSERT, c.ASSERT_NOT):
        return [av[1]]
    if op == c.ATOMIC_GROUP:
        return [av]
    return []


def _walk(parsed: Any, in_repeat: bool) -> str | None:
    """Catastrophic-backtracking shapes: a repeat inside a repeat, or a back-reference."""
    from re import _constants as c  # noqa: PLC0415

    for op, av in parsed:
        if op in (c.GROUPREF, c.GROUPREF_EXISTS):
            return "back-reference"
        if op in (c.MAX_REPEAT, c.MIN_REPEAT, c.POSSESSIVE_REPEAT):
            _lo, hi, sub = av
            many = hi is c.MAXREPEAT or hi > 1
            if many and in_repeat:
                return "nested quantifier"
            subs, inner = [sub], in_repeat or many
        else:
            subs, inner = _children(op, av), in_repeat
        for sub_pattern in subs:
            if (p := _walk(sub_pattern, inner)) is not None:
                return p
    return None


def regex_problem(pattern: str) -> str | None:
    """None when `pattern` is a safe anchored address regex (≤ 200 chars, no back-references or nested quantifiers)."""
    from re import _parser  # noqa: PLC0415 - the stdlib's own parse tree, so the check sees what `re` will run

    if len(pattern) > MAX_PATTERN:
        return f"pattern longer than {MAX_PATTERN} chars"
    if not pattern.startswith("^"):
        return "pattern must be anchored with ^"
    try:
        tree = _parser.parse(pattern)
    except re.error as e:
        return f"bad regex: {e}"
    return _walk(tree, False)


def _field_errors(spec: ParserSpec) -> list[str]:
    errs: list[str] = []
    seen: dict[str, set[str]] = {}
    for i, f in enumerate(spec.fields):
        where = f"fields[{i}] {f.attribute}"
        if f.attribute not in specs.ATTRS:
            errs.append(f"{where}: unknown attribute")
            continue
        for name in ("unit", "prefer_unit"):
            u = getattr(f, name)
            if u is not None and not _attr_unit_ok(f.attribute, u):
                errs.append(f"{where}: {name} {u!r} is not a known unit for this attribute")
        if f.css is not None:
            if spec.layout != "css":
                errs.append(f"{where}: a css field needs layout 'css'")
            if p := _selector_problem(f.css):
                errs.append(f"{where}: {p}")
        if f.jsonld is not None and not _JSONLD.fullmatch(f.jsonld):
            errs.append(f"{where}: bad JSON-LD path {f.jsonld!r}")
        ident = norm_label(f.label) if f.label is not None else f.css or f.jsonld or ""
        if ident in seen.setdefault(f.attribute, set()):
            errs.append(f"{where}: the same attribute twice with the same label/selector")
        seen[f.attribute].add(ident)
    return errs


def _layout_errors(spec: ParserSpec) -> list[str]:
    errs: list[str] = []
    if spec.layout == "css":
        for name in ("row_css", "label_css", "value_css"):
            sel = getattr(spec, name)
            if not sel:
                errs.append(f"layout 'css' needs {name}")
            elif p := _selector_problem(sel):
                errs.append(f"{name}: {p}")
    for pat in spec.url_patterns:
        if p := regex_problem(pat):
            errs.append(f"url_patterns {pat[:60]!r}: {p}")
    return errs


def _domain_problem(d: str, sources: Mapping[str, Mapping[str, Any]] | None, deny: tuple[str, ...]) -> str | None:
    if any(x and x.lower() in d for x in deny):
        return "on the deny-list"
    if sources is None:
        return None
    src = sources.get(d)
    if src is None:
        return "not a registry source"
    if str(src.get("access", "unknown")) != "ok":
        return f"registry access is {src.get('access')!r}, not 'ok'"
    if src.get("frozen"):
        return "frozen by the owner"
    if str(src.get("status", "")) == "blocked":
        return "blocked"
    return None


def _semantic(spec: ParserSpec, sources: Mapping[str, Mapping[str, Any]] | None, deny: tuple[str, ...]) -> list[str]:
    errs = _field_errors(spec) + _layout_errors(spec)
    errs += [f"domain {d}: {p}" for d in spec.domains if (p := _domain_problem(d, sources, deny))]
    size = len(spec.model_dump_json().encode("utf-8"))
    if size > MAX_BYTES:
        errs.append(f"spec is {size} bytes, over 20 KB")
    return errs


def _pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"])
        msg = "extra key not allowed" if err["type"] == "extra_forbidden" else err["msg"]
        out.append(f"{loc or 'spec'}: {msg}")
    return out


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
