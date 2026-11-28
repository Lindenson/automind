# Audit: where the system looks for car data today, and the external sources (2026-11-28)

Paths under `backend/src/automind/` and `backend/config/`.

## Identification today

- `chat/application/services/identification/service.py`: make normalised (:75-78) → known models = catalogue ∪
  `config/generations.yaml` ∪ the make's Spanish line-up (`stages/catalogue_lookup.py:17-31`; abroad: Europe → home
  market → anywhere, `stages/place_market.py:72-88`) → place on market, year first (used) → **SourcedVersions →
  CatalogueRows → OpenWorld** (:67, :117-121) → `verify_proposal`.
- `versions.lookup`: cache `model_versions` (TTL 60 days, written as market ES always,
  `chat/infrastructure/persistence/repositories.py:583,602`) → abroad queries → (new car) EEA only for a facelift year
  → two open Spanish searches (`gama motores versiones CV precios`, `ficha técnica`) → (new car) harder queries incl.
  one `site:` of the registry's top-3 spec sources → **last**: the list from EEA registrations (combustion only, not
  cached) → since PR #163: a named version searched on its own (`named_version.py`).
- Web reader (`acquisition/identity_readers/web.py`): `_read` sorts URLs by `_rank` (official **or make in host**
  +3, km77 +2, range words +1, one-version page −4), reads ≤ 6 of 12, keeps the `_richest` 3 by the count of CV
  figures (the rank is lost here); `versions.validate` checks power in excerpt, excerpt in page, years; ≥ 3 versions
  → stored.
- Datasets (`identity_readers/application/dataset_versions.py`): stored gold → `search_cache` → one live EEA query;
  only `eea_co2` wired; RDW loaders exist (`acquisition/gold/infrastructure/loaders/rdw.py`) but are not used here.
- Line-up (`lineup.py`): cache 30 days; maker's **home page** + top-4 of `"{make} gama modelos precios España"`, ≤ 2
  pages; accepted when a source is official **or states a price** (a dealer passes).
- Resolver (`web.generation_hints`): line-up page, user URL, top-5 of an EN open search, top-2 pages read; no
  authority order.
- Caches: `model_versions` 60 d, `brand_lineups` 30 d, `search_cache` 7 d (prices 3 d, empty 6 h), page store per
  area (specs 365 d; ERROR 6 h, REFUSED 30 d), `vehicle_variants` no TTL.

## Tier-like notions that exist

- `shared/evidence/sources.py:13` `AUTHORITY` = MANUFACTURER > INSTRUMENTED_TEST > PUBLICATION > ENCYCLOPEDIA >
  SPEC_DATABASE; `classify_source` (:89-103). Used in research ranking (`acquisition/pipeline/locate.py:144`, key
  favourite priority → authority → search rank) and value selection (`evidence/selection.py:112,126`). **Not used in
  identification.** No DEALER / CLASSIFIED / REGISTRY type.
- Research rounds (`shared/research_order/search_plan.py:210-254`): round 0 = `site:` favourites (maker first for
  ES price/specs/maintenance), then open templates, registry `site:`, AI queries. Registry `sources_for`: active →
  candidates, market order, score (`acquisition/registry/domain/planning.py:216-227`).

## Weak points

1. A dealer page becomes the list (≥ 3 versions, cached 60 d); `_richest` favours stock tables.
2. Make-in-host = official bonus (bmwmadrid.es ranks like bmw.es), contrary to `is_official`.
3. `_rank` order dropped after reading.
4. Official one-version data sheets penalised like any one-version page.
5. Maker sites: no JS, failures cached; line-up reads the home page only; no press / price-list fallback.
6. Line-up: "states a price" counts like official.
7. Resolver: EN open search in raw order.
8. Datasets last, combustion only, not cached; RDW not wired; SPEC_DATABASE ranked lowest.
9. `model_versions` market always ES.
10. Registry `site:` only as the third harder query of new cars.

Plug-in points for a tier: `evidence.tier_of` beside `classify_source` + `config/sources.yaml tiers:`; `web.py`
`_rank`/`_richest`/`_read`/`lineup`/`generation_hints`; `versions.lookup` order and `_from_docs` acceptance;
`lineup.validate`; `service.py:67` fallback order; `locate.py:144`; `search_plan` rounds; registry priors;
`selection.py:126`; `identity_readers/infrastructure/wiring.py` (more datasets).

## External sources (each checked on its own pages, 2026-11-28)

| Source | License | EU / Spain at version level? | Access, freshness | Verdict |
|---|---|---|---|---|
| VehiclesDB (github.com/vehiclesdb/vehiclesdb) | data CC-BY-4.0 (attribution), code MIT | **No** — make/model only (321 car makes, 6,043 models); generations and variants "reserved", specs a future paid API; Spain from DGT | free GitHub releases (no account), CSV/JSON/Parquet/SQLite, Python SDK, MCP in the Ruby gem; several releases a month; project since 2026-06 | id/alias skeleton only |
| carscatalogue ("World Vehicle Database") | **none** | README only, no data files | 3 commits, 0 stars | unusable |
| @meterapp/vehicle-db | ISC (npm metadata), per-source terms | No — make/model/year | npm 2.88.0, 2026-11-27; marketing for carimage.dev | not needed |
| NHTSA vPIC | US public domain | No (US market; WMI decoding only) | REST, rate-controlled, DB downloads | not needed |
| Wikidata | CC0 | No engines; BMW 3 Series misses E21/E36/F30/G20 | SPARQL | aliases only |
| JATO Specifications | commercial | trim level, 50+ markets, option prices (Spain unconfirmed) | trial via developer portal | owner's call |
| Autovista / Eurotax (Schwacke) | commercial | version specs + residuals, lists Spain | quote | owner's call |
| auto-data.net API | commercial | 55k specs, > half European | test before buying | owner's call |
| CarQuery | — | — | site unreachable | dead |
| **EEA CO2 cars** | EEA reuse (CC BY 4.0 by default; confirm on the dataset page) | **Yes**: make, commercial name, type/variant/version, kW, cc, fuel, year, per member state with counts; new registrations from 2010; no prices; `Cn` messy | yearly (2025 provisional 2026-06-25), bulk CSV + Discodata SQL (502 on 2026-11-28) | tier 1, bulk-load |
| **DGT MATRABA** (Spain) | Spanish public reuse notice (attribution; to confirm) | **Yes**: marca/modelo/tipo/variante/versión ITV, kW, cc, per registration | monthly (+ daily); VIN removed since 2025-02 | tier 1 for Spain |
| **RDW** (NL) | CC0 | **Yes**: handelsbenaming ("320D"), type/variant/uitvoering, cc, list price (`catalogusprijs`); power in `8ys7-d773` | daily, Socrata API | tier 1 cross-check |
| KBA FZ10 (DE) | DL-DE/BY-2.0 | make + model series only | — | no |
| ADEME Car Labelling (FR) | unverified | unverified | updated 2026-07-28 | later |
| UK VCA car fuel data | Crown copyright | — | availability unverified | later |
| Hacienda price tables (ES, Orden HAC/1501/2025) | official | make/model/cc/kW → tax-basis price | yearly PDF | prices, later |
