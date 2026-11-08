"""The semantic check of a parser spec (spec 011 contracts/parser-spec.md "Validation"): attributes and units the
domain knows, selectors selectolax accepts, safe address regexes, JSON-LD paths, domains the registry allows, and the
size limit. Pure; `ParserSpec.check` calls `problems`."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from selectolax.lexbor import LexborHTMLParser  # the parser the interpreter uses

from automind.acquisition.parsing.normalise.labels import norm_label
from automind.acquisition.parsing.readers.regex_safety import regex_problem
from automind.shared.vehicle import specs, units
from automind.shared.vehicle.specs.registry import TEXT

if TYPE_CHECKING:
    from automind.acquisition.parsing.readers.spec import ParserSpec

MAX_BYTES = 20 * 1024
_JSONLD = re.compile(r"[A-Za-z@_][\w@]*(\.[A-Za-z@_0-9][\w@]*)*")  # "vehicleEngine.enginePower.value"


def problems(spec: ParserSpec, sources: Mapping[str, Mapping[str, Any]] | None, deny: tuple[str, ...]) -> list[str]:
    """Every semantic problem of a schema-valid spec; [] = valid. `sources` maps registry domains to
    `{access, frozen, status}` (None skips the registry check); `deny` is the deny-list."""
    errs = _field_errors(spec) + _layout_errors(spec)
    errs += [f"domain {d}: {p}" for d in spec.domains if (p := _domain_problem(d, sources, deny))]
    size = len(spec.model_dump_json().encode("utf-8"))
    if size > MAX_BYTES:
        errs.append(f"spec is {size} bytes, over 20 KB")
    return errs


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


def _attr_unit_ok(attribute: str, unit: str) -> bool:
    a = specs.ATTRS.get(attribute)
    if a is None or a.kind == TEXT:
        return a is not None
    if a.convert is None:
        return True
    try:
        a.convert(1.0, unit)
    except (units.UnitError, ValueError):
        return False
    return True


def _selector_problem(sel: str) -> str | None:
    try:
        LexborHTMLParser("<p></p>").css(sel)
    except Exception as e:  # noqa: BLE001 - selectolax raises plain exceptions on bad selectors
        return f"bad CSS selector {sel!r}: {e}"
    return None


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
