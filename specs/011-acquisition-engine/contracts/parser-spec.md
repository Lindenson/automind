# Contract: Parser specification (`automind.acquisition.parsing.spec.ParserSpec`)

The only form in which a site reader can change (constitution XII). An agent's proposal is this JSON; it is validated
before any gate. The interpreter that executes it is fixed code (`acquisition/parsing/interpreter.py`).

```python
class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribute: str                       # ∈ domain.specs.ATTRS
    label: str | None = None             # label text, matched after lowercasing, ":" and whitespace removal
    prefix: bool = False                 # label matches the start of the cell text
    css: str | None = None               # selector of the value element (layout "css" only)
    jsonld: str | None = None            # dotted path into the page's JSON-LD (e.g. "vehicleEngine.enginePower.value")
    unit: str | None = None              # force this unit (must be known to domain.units)
    prefer_unit: str | None = None       # when a cell lists several units, take the number before this one
    text: bool = False                   # keep the cell as text (drivetrain, gearbox)
    # exactly one of label / css / jsonld


class ParserSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reader: str                          # ^[a-z0-9_]{2,40}$
    version: int                         # ≥ 1, = previous active + 1 for a proposal
    domains: list[str]                   # 1..5 registrable domains; each a registry source with access "ok"
    url_patterns: list[str] = []         # anchored regexes ≤ 200 chars; no backrefs, no nested quantifiers
    page_type: Literal["spec_table"] = "spec_table"
    layout: Literal["table", "divrow", "dl", "css"]
    row_css: str | None = None           # layout "css": repeating row selector
    label_css: str | None = None         # layout "css": label inside a row
    value_css: str | None = None         # layout "css": value inside a row
    fields: list[FieldRule]              # 1..60
    min_rows: int = 3                    # fewer matched rows → no reading (falls back to the extractor)
    skip_values: list[str] = ["-", "No disponible"]
    notes: str = ""                      # ≤ 500 chars, shown in the Changes tab
```

## Validation (`ParserSpec.check(registry, units) -> list[str]`, empty = valid)

- every `attribute` in `specs.ATTRS`; no attribute twice unless the labels differ (alternatives for one attribute);
- every unit known to `domain.units`; every CSS selector compiles in selectolax; every regex passes the safety check;
- domains are registry sources, not blocked, not deny-listed, not frozen;
- size: serialised JSON ≤ 20 KB.

## v1 migration (from `config/site_readers.yaml`)

| YAML | Spec |
|---|---|
| top-level key (`km77`) | `reader` |
| `domains` | `domains` |
| `pairs: table` / `divrow` | `layout: table` / `divrow` |
| `labels: {"potencia máxima": {attribute: max_power, prefer_unit: kW}}` | `fields: [{label: "potencia máxima", attribute: max_power, prefer_unit: kW}]` |
| `prefix`, `unit`, `text` | same names |
| `MIN_ROWS = 3` (code) | `min_rows: 3` |
| `("-", "No disponible")` (code) | `skip_values` |

Equivalence: for every fixture page and stored snapshot, `interpreter.read(spec_v1, html)` returns the same
`(attribute, raw_value, raw_unit, excerpt)` rows, in the same order, with the same `ambiguous` flag, as
`site_readers.read_pairs` (test `tests/unit/test_parser_v1_equivalence.py`).
