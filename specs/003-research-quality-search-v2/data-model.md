# Data Model: Research Quality and Search v2

Changes on top of the 002 model (`specs/002-conversational-mvp/data-model.md`). One Alembic
migration `0005_search_v2`. **Shared** = knowledge about cars, reused by all chats; **chat-scoped** =
removed when the chat is deleted (FR-028, FR-029).

## New tables

### `search_cache` (shared)

| Column | Type | Notes |
|---|---|---|
| key | char(64) PK | sha256(provider \| normalised query \| gl \| hl \| num) |
| provider | varchar(20) | `serper`, `tavily`, … |
| query | text | as sent |
| gl, hl | varchar(8) | market / language |
| hits | jsonb | `[{url, title, snippet, rank}]` (deny-listed URLs already removed) |
| fetched_at | timestamptz | |
| expires_at | timestamptz | index; default fetched_at + 7 days (config) |

Validation: query normalisation = lowercase, collapsed spaces, sorted `site:` group. Hits never hold
page text.

### `page_relevance` (shared)

Relevance verdict of a page for a variant (FR-013). A page can be relevant for one variant and not
for its sibling.

| Column | Type | Notes |
|---|---|---|
| document_id | FK documents | PK part |
| variant_id | FK vehicle_variants | PK part |
| verdict | varchar(16) | `RELEVANT`, `OTHER_VARIANT`, `MULTI_VARIANT`, `NOT_ABOUT_CAR`, `UNCERTAIN` |
| other | varchar(80) null | e.g. "J250 (2024–)" |
| reason | text | human-readable, shown in the source list |
| method | varchar(12) | `RULES` or `LLM` |
| created_at | timestamptz | |

### `used_price_ranges` (shared)

Editorial used-price ranges (FR-022, clarification Q1 = C).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| variant_id | FK vehicle_variants | generation-level ranges are stored on each variant of the generation they name |
| evidence_id | FK evidence | source article (never a classified, enforced by deny-list) |
| model_year_from, model_year_to | int null | years the range applies to |
| min_eur, max_eur | numeric(10,0) | normalised to EUR with the configured rate if quoted in GBP |
| market | varchar(4) | ES/GB/DE |
| quoted_on | date null | article date if found |
| excerpt | text | verbatim, validated like any claim |
| status | varchar(32) | `ACCEPTED`, `REJECTED_*` |

### `site_reader_stats` (shared, operator metric)

| Column | Type | Notes |
|---|---|---|
| domain | varchar(200) | PK part |
| day | date | PK part |
| ok, failed, ambiguous | int | FR-009, SC-005 |

### `feasibility_checks` (chat-scoped)

Persisted computation (constitution III/IX: inputs and outputs of deterministic computations).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| chat_id, turn_id | varchar(36) | index on chat_id |
| variant_id | FK vehicle_variants | |
| check | varchar(16) | `BUDGET`, `RUNNING_COST`, `USAGE_SPACE`, `USAGE_POWER`, `USAGE_RANGE` |
| verdict | varchar(16) | `FITS`, `DOES_NOT_FIT`, `USED_ONLY`, `OTHER_CLASS`, `UNKNOWN` |
| details | jsonb | numbers compared, age range, provenance per number, missing data, rule version |
| created_at | timestamptz | |

### `deleted_chats` (audit, no content)

| Column | Type | Notes |
|---|---|---|
| chat_id | varchar(36) PK | tombstone: WS/REST answer "deleted" (FR-030) |
| deleted_at | timestamptz | |
| counts | jsonb | rows removed per table |

## Changed tables

### `documents` → page store (shared)

New columns: `url_hash char(64) unique` (sha256 of the normalised final URL), `final_url text`,
`status varchar(16)` (`OK`, `NO_CONTENT`, `REFUSED`, `ERROR`), `fail_reason text null`,
`content_type varchar(60)`, `reader varchar(40)` (`main_content`, `pdf`, `site:km77`, …),
`fetched_at timestamptz`, `expires_at timestamptz` (index), `bytes int`. Existing rows: `url_hash`
backfilled from `url`, `expires_at = retrieved_at + 365 days`. The store keeps one row per URL, so
the unique constraint on `content_sha256` becomes a plain index (two URLs may serve the same text).

Retention: rows with `expires_at < now()` **and** no `evidence.document_id` reference are deleted
(FR-026). Referenced rows are kept (provenance) but treated as stale for reuse.

### `claims` (shared)

New status values: `REJECTED_IMPLAUSIBLE` (rule id in new column `reject_rule varchar(40)`),
`REJECTED_OTHER_VARIANT`, `REJECTED_OTHER_MARKET`, `REJECTED_OTHER_YEAR`, `REJECTED_AMBIGUOUS`.
New column `extracted_by varchar(12)` (`READER` or `LLM`) for SC-005.

### `evidence` (shared)

New column `favourite boolean default false` and `favourite_priority smallint null` (FR-012).

### `research_jobs` (chat-scoped, as in 002)

New columns: `queries jsonb` (sent, with round and kind FAVOURITE/OPEN/AI), `pages_found int`,
`pages_cached int`, `pages_rejected jsonb` ({reason: n}), `values_rejected jsonb` ({reason: n}),
`reader_values int`, `search_cost_eur numeric(10,4)`.

### `search_calls` (chat-scoped)

New column `cached boolean default false`; `provider` values extend to `serper`. Cache hits are
recorded with `cost_eur = 0` so SC-006 is measurable.

### `chats`

No column change; deletion is a hard delete plus a `deleted_chats` tombstone.

## Case file (JSON in `case_files.data`)

```text
constraints:
  budget: {amount: number, currency: "EUR"|"GBP"|"USD"|null, intent: NEW|USED|ANY|UNKNOWN,
           kind: TOTAL|MONTHLY} | null
  running_cost_limit: {amount: number, period: MONTH|YEAR} | null
  usage: {mountains: bool|null, towing_kg: int|null, passengers: int|null,
          luggage: LOW|MEDIUM|HIGH|null, city_share: 0..1|null, daily_km: int|null,
          climate: COLD|HOT|MIXED|null}
  evidence: [string]          # verbatim words from user messages that set these values
feasibility_ack: string|null  # fingerprint of (constraints, verdicts) the user acknowledged
asked: [..., BUDGET_INTENT, BUDGET_CURRENCY, BUDGET_KIND]   # new question kinds
```

`annual_km` stays where it is (002). `CaseDelta` gains `set_constraints` (partial update) and
`constraints_evidence`; code drops any number not present in `constraints_evidence` (R10).
The `fingerprint` used to avoid repeated reports (002 FR-004) includes `constraints`.

## Research areas

`AREAS` gains `used_price` (freshness 30 days). Minimum: ≥ 1 accepted editorial range for the
requested model years, or the area is "insufficient data" and the feasibility check falls back to
the labelled depreciation estimate.

## Configuration files (data, not code)

| File | New / changed | Content |
|---|---|---|
| `config/search.yaml` | new | provider order, `num`, per-area result count, cache TTL, market → gl/hl, max AI follow-up queries |
| `config/sources.yaml` | changed | `favourites:` list (domain, source_type, areas, markets, priority, reader, tos_checked); deny-list unchanged |
| `config/queries.yaml` | changed | per area: `favourite` template (with `{sites}`), `open` templates (existing), languages |
| `config/site_readers.yaml` | new | per site: label → canonical attribute + unit mapping |
| `config/plausibility.yaml` | new | ranges per attribute × powertrain/class, cross-checks |
| `config/feasibility.yaml` | new | depreciation curves by class, usage thresholds, currency rates (labelled assumptions) |
| `config/models.yaml` | changed | roles `query_planner`, `relevance` |
| `config/prices.yaml` | changed | `search.serper.per_query`, provider-specific search prices |

## State transitions

Page: `(none) → FETCHED(OK|NO_CONTENT|REFUSED|ERROR) → [expired] → refetched | deleted by retention`.

Relevance per (page, variant): `RULES verdict → (UNCERTAIN) → LLM verdict`; only `RELEVANT` and the
isolated part of `MULTI_VARIANT` proceed to reading/extraction.

Claim: `extracted (READER|LLM) → unit normalised → plausibility → excerpt check → [validator] →
ACCEPTED | REJECTED_*` → selection (002 rules).

Turn with constraints: `… → research → feasibility → FEASIBILITY (await ack) → REPORT`, or `ASK
(BUDGET_INTENT)` before research when intent is unknown and matters.

Chat: `active → deleting (turn cancelled) → deleted (tombstone)`.
