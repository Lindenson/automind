# Contract: Search Port, Page Store and Configuration (internal)

Internal contracts between `application/` and `infrastructure/` (constitution V: application
depends only on domain and ports). Fakes in `tests/fakes/` implement the same ports.

## Ports (`application/ports.py`)

```python
@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str
    rank: int

class SearchProvider(Protocol):
    name: str
    async def search(self, query: str, *, gl: str, hl: str, num: int = 10) -> list[SearchHit]: ...

class Searcher(Protocol):
    """Cache-first search over the configured providers (search_cache → primary → fallback).
    Records usage (cost 0 for cache hits). Drops deny-listed URLs. Raises SearchUnavailable only
    when every provider failed."""
    async def search(self, query: str, *, market: str, area: str) -> list[SearchHit]: ...

@dataclass(frozen=True)
class Page:
    url: str              # final URL
    title: str
    text: str             # main content (markdown, tables kept) or PDF text
    content_type: str
    reader: str           # "main_content" | "pdf" | "site:<id>"
    fetched_at: datetime
    from_cache: bool
    html: str | None      # kept in memory only for site readers; never stored

class PageStore(Protocol):
    """Cache-first fetch under the fetch policy (deny-list, robots incl. Crawl-delay, rate, size).
    Returns None with a stored reason when refused or empty."""
    async def get(self, url: str, *, area: str) -> Page | None: ...

class SiteReaders(Protocol):
    def read(self, page: Page, target: VariantIdentity) -> SiteReading | None: ...
```

`SiteReading = {rows: [(attribute, raw_value, raw_unit, excerpt)], ambiguous: bool, reader: str}`.

The 002 `Search` port (`search/extract/fill_full_text`) is replaced; pasted URLs use `PageStore.get`.

## Pure domain functions (new)

| Module | Function | Contract |
|---|---|---|
| `domain/relevance.py` | `judge(page_facts, target, siblings) -> Relevance` | deterministic; `UNCERTAIN` when signals conflict or are absent |
| `domain/plausibility.py` | `check(attribute, value, unit, ctx, rules) -> PlausibilityResult` | `ok` or `rule_id`; rules injected (from config) |
| `domain/feasibility.py` | `evaluate(constraints, cars, rules) -> list[CarFeasibility]` | deterministic; every number with provenance; `UNKNOWN` lists missing inputs |
| `domain/search_plan.py` | `queries(area, identity, market, favourites, templates, round) -> list[PlannedQuery]` | favourite groups (≤ 4 sites each) first; open-web only for round ≥ 1 or when asked |
| `domain/policy.py` | `decide(...)` | adds `ASK(BUDGET_INTENT…)` and `FEASIBILITY` (see research R12) |

## Configuration schemas

### `config/search.yaml`

```yaml
version: 1
provider: serper            # serper | tavily | parallel | brave
fallback: [tavily]          # tried in order when the provider fails or has no credit
num: 10                     # results per query
cache_ttl_days: {default: 7, price: 3}
markets:                    # case market/language → provider locale
  ES: {gl: es, hl: es}
  EN: {gl: gb, hl: en}
  DE: {gl: de, hl: de}
ai_followup: {max_queries_per_area: 3, depths: [DEEP, STANDARD]}
limits: {max_pages_per_job: 8, max_fetch_bytes_per_turn: 40000000}
```

### `config/sources.yaml` (added section)

```yaml
favourites:
  - {domain: km77.com, source_type: SPEC_DATABASE, areas: [specs, engineering, measured, price, maintenance, reviews, used_price],
     markets: [ES], priority: 1, reader: km77, tos_checked: null}
  - {domain: ultimatespecs.com, source_type: SPEC_DATABASE, areas: [specs, engineering], markets: [ANY],
     priority: 1, reader: ultimatespecs, tos_checked: null}
  # … (initial list in research.md R5)
```

A reader runs only when `tos_checked` is a date (the operator reviewed the site's terms).

### `config/queries.yaml` (changed shape)

```yaml
specs:
  favourite: "{make} {model} {generation} {variant} {sites}"
  open:
    - "{make} {model} {generation} {variant} specifications power torque weight 0-100"
    - "{make} {model} {generation} {variant} ficha técnica peso potencia par"
used_price:
  favourite: "{make} {model} {generation} {years} used price buying guide {sites}"
  open:
    - "{make} {model} {generation} segunda mano precio cuánto cuesta guía de compra"
    - "{make} {model} {generation} used buying guide how much to pay"
```

### `config/site_readers.yaml`

```yaml
km77:
  table_selector: "table.table-specs"         # illustrative; fixed during implementation from real pages
  labels:
    "Potencia máxima": {attribute: max_power, unit_from_value: true}
    "Par máximo": {attribute: max_torque}
    "Peso en orden de marcha": {attribute: curb_mass}
    "Aceleración 0-100 km/h": {attribute: claimed_0_100}
```

### `config/plausibility.yaml`

```yaml
version: 1
ranges:
  curb_mass: {min: 600, max: 3800, unit: kg}
  max_power: {min: 30, max: 1200, unit: kW}
  measured_0_100: {ICE: {min: 2.3, max: 25}, BEV: {min: 1.9, max: 20}, unit: s}
  boot_volume: {min: 50, max: 2500, unit: l}
  price_eur: {min: 5000, max: 600000}
cross:
  - {id: pw_ratio, rule: "max_power / curb_mass <= 1.0"}
```

### `config/feasibility.yaml`

```yaml
version: 1
depreciation:               # share of the new price left at age (years); labelled ASSUMPTION
  small:   {1: 0.80, 3: 0.62, 5: 0.48, 8: 0.33, 12: 0.20, 15: 0.14}
  compact: {1: 0.78, 3: 0.60, 5: 0.47, 8: 0.33, 12: 0.20, 15: 0.14}
  mid_large: {1: 0.75, 3: 0.55, 5: 0.42, 8: 0.28, 12: 0.17, 15: 0.12}
  premium_suv_4x4: {1: 0.80, 3: 0.63, 5: 0.50, 8: 0.36, 12: 0.24, 15: 0.18}
usage:
  boot_l_per_passenger_with_luggage: {LOW: 60, MEDIUM: 100, HIGH: 140}
  min_kw_per_t: {mountains: 60, towing_per_1000kg: 75}
  bev_range_margin: 1.6      # daily_km × margin ≤ WLTP range
currency_to_eur: {GBP: 1.17, USD: 0.92}   # labelled assumption; updated by the operator
```

All numbers above are starting values to be reviewed during implementation; they are data, not
code.
