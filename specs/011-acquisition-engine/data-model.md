# Data Model: Spec 011

All tables in PostgreSQL next to the existing ones (latest migration `0017`). Timestamps are `timestamptz`; ids are
`String(36)` uuids like the rest of `infrastructure/db/models.py`. JSONB where noted. One migration per stage, so each
stage ships with only its own schema. Version identifiers are text (research R2): `km77@v1`,
`extract_specs@v3`, `google_genai:gemini-3.1-flash-lite`, `plan@1`.

## Migration 0018 — snapshots and producer versions (US1)

### `snapshot_blobs`
| Column | Type | Note |
|---|---|---|
| sha256 | char(64) PK | of the raw body |
| codec | text | `zstd` |
| body | bytea | compressed; `STORAGE EXTERNAL` |
| raw_bytes | int | |
| stored_bytes | int | |
| created_at | timestamptz | |

### `page_snapshots`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| url | text | as requested |
| url_hash | char(64), index | same hash as `documents.url_hash` |
| final_url | text null | after redirects |
| domain | text, index | registrable domain |
| document_id | uuid null FK documents (set null) | the cache row the fetch produced |
| fetched_at | timestamptz, index | |
| blob_sha256 | char(64) null FK snapshot_blobs | null when not replayable |
| content_type | text | |
| http_status | int null | |
| status | text | `OK, NO_CONTENT, REFUSED, ERROR` (as `documents.status`) |
| replayable | bool | false for NO_CONTENT/REFUSED/ERROR, paywall, js_only |
| retention_class | text | `plain, accepted, pinned` |
| keep_until | timestamptz, index | fetched_at + 30 d (plain) / 180 d (accepted); null while pinned |
| accepted_values | int default 0 | updated when claims from this page are accepted |
| variant_ids | text[] default '{}' | variants the page was judged relevant for / used for |
| structure_hash | char(16) null | research R11, filled by the parser adapter (US4) |
| parser_version | text null | reader version that read it, if any |

Rules: written by the page store on every network fetch (never on a cache hit); `retention_class` becomes `accepted`
when `accepted_values > 0`; `pinned` while an experiment references it (`acq_experiments.corpus`); the worker's
retention removes rows past `keep_until` and enforces `snapshots.max_gb` (research R1), then orphan blobs.

### `claims` (altered)
| Column | Type | Note |
|---|---|---|
| producer | text default `extractor` | `reader, extractor, dataset, user` (back-filled from `extracted_by`: READER→reader, LLM→extractor) |
| producer_version | text null | `km77@v1` or `extract_specs@v3` (back-fill: readers `<reader>@v1`; LLM claims `legacy`) |
| model | text null | served model for extractor claims; null for readers |
| snapshot_id | uuid null FK page_snapshots (set null), index | |

`extracted_by` stays (read by challenge/blame) until US3 replaces its uses; then a later spec drops it.

### `registry_attempts` (altered)
`producer_version text null`, `model text null`, `snapshot_id uuid null`, `stage_versions jsonb default '{}'`
(`{"plan": "plan@1", "locate": "locate@1", …}`), `searches int default 0` (searches spent for this page's query
group; feeds R7's searches-per-value).

### `page_relevance` (altered)
`prompt_version text null`, `model text null` (method `LLM` only).

### `research_runs` (altered)
`stage_versions jsonb default '{}'`.

## Migration 0019 — gold values (US1)

### `gold_datasets`
| Column | Type | Note |
|---|---|---|
| id | text PK | `eea_co2_2024`, `eea_obfcm_2023`, `rdw`, `reference_set`, `challenges` |
| name | text | |
| kind | text | `eea_co2, eea_obfcm, rdw, kba, reference_set, challenge` |
| version | text | dataset year / release date / file hash |
| licence | text | `CC-BY-4.0`, `CC0`, `DL-DE-BY-2.0`, `internal` |
| url | text | download/API endpoint |
| rows_read, rows_matched | int | |
| loaded_at | timestamptz | |
| next_refresh_at | timestamptz null | |
| error | text null | last failure |

### `gold_values`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| variant_id | uuid FK vehicle_variants (cascade), index | |
| attribute | text | canonical attribute (`specs.ATTRS` + `consumption_wltp`, `consumption_real`, `co2_wltp`, `energy_wh_km`, `range_wltp_km`, `list_price_nl`) |
| value_num | float null | canonical unit |
| value_text | text null | |
| unit | text | explicit (III) |
| tolerance | float | absolute or relative per `config/gold_datasets.yaml: tolerances` (stored for reproducibility) |
| tolerance_kind | text | `abs`, `rel` |
| origin | text | `dataset`, `challenge`, `reference_set` |
| dataset_id | text null FK gold_datasets | |
| record_key | text null | dataset group key (make/name/fuel/kW) or challenge id |
| match_rule | text | `exact`, `by_power`, `challenge_confirmed`, `challenge_corrected`, `reference_set`, + conversion rule e.g. `eu_running_order_minus_driver` |
| confidence | text | `HIGH`, `MEDIUM` |
| registrations | int null | weight of the group |
| verified_at | timestamptz | |
| flagged | bool default false | contradicted by ≥ 2 independent families (research R3) |
| flag_reason | text null | |
| unique (variant_id, attribute, origin, dataset_id) | | newest load replaces |

### `extraction_cache`
`prompt_hash char(12), model text, blob_sha256 char(64), area text, output jsonb, created_at`; PK `(prompt_hash,
model, blob_sha256, area)`. Replay/shadow of extractor versions only (created with gold in US1 so extractor replay is cached from the start); retention 60 days.

## Migration 0020 — task queue and worker (US2)

### `acq_tasks`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| kind | text | `prefetch, rollup, drift, registry_review, insight_run, metrics_snapshot, retention_snapshots, gold_load, baseline, scout, parser_doctor, rule_auditor, extractor_tuner, evaluator, gate_replay, gate_shadow, watch, blame_judge, replay` |
| dedupe_key | text unique | e.g. `rollup:2026-11-05`, `doctor:km77@v1` |
| payload | jsonb | |
| priority | smallint default 5 | lower first |
| state | text | `queued, running, done, failed, dead` |
| run_at | timestamptz, index (state, priority, run_at) | |
| attempts | smallint default 0 | |
| max_attempts | smallint default 3 | |
| lease_until | timestamptz null | |
| locked_by | text null | worker id |
| last_error | text null | |
| result | jsonb null | |
| cost_eur | numeric(10,4) default 0 | LLM spend of the task |
| created_at, started_at, finished_at | timestamptz | |

Retention: `done` older than 30 days and `dead` older than 90 days deleted by the worker.

### `acq_workers`
`id text PK, host text, pid int, version text (git commit or image tag), started_at, beat_at, tasks_done int`.

## Migration 0021 — honest reputation (US3)

### `capabilities` (altered)
`signals_w real default 0` (decayed sum of accuracy-signal weights, priors excluded),
`families_agree real default 0` (decayed count of family agreements),
`explore_spent_eur real default 0` (today's exploration spend, reset by the roll-up).

### `truth_signals` (altered)
`kind` adds `physics`; `blame_vector jsonb null` (`{"parser": 1.0}` or `{"relevance": 0.5, "extractor": 0.5}`),
`component text null` (`parser:km77@v4`, `extractor:extract_specs@v3|<model>`, `rule:<id>`, `fusion:merge@1`,
`source:<domain>`), `gold_id uuid null`, `snapshot_id uuid null`, `disputed bool default false`.

### `component_reputation`
| Column | Type | Note |
|---|---|---|
| kind | text | `parser, extractor, relevance, rule, fusion` |
| key | text | `km77@v4`, `extract_specs@v3|google_genai:gemini-3.1-flash-lite`, `sense.engine_vs_system_torque`, `merge@1` |
| right_w, wrong_w | real | decayed |
| acc_lb | real | Wilson lower bound |
| decayed_at | timestamptz | |
| PK (kind, key) | | |

### `acq_daily`
`day date, area text, market text, searches int, pages int, accepted_values int, wrong_values int,
gold_checked int, gold_wrong int, cost_eur numeric(10,4), explore_eur numeric(10,4)`; PK `(day, area, market)`.
Feeds searches-per-accepted-value (SC-009) and the accuracy KPI.

### `kpi_baselines`
`id uuid PK, name text (e.g. "pre-autonomy"), started_at, ended_at, values jsonb ({accuracy_share_wrong: {area: x},
satisfaction_index, nodata_share: {area: x}, searches_per_value: {area: x}, coverage}), recorded_at, note text`.

## Migration 0022 — parser specifications, drift and the change journal (US4)

### `parsers`
`reader text PK (km77), domains text[], page_type text, active_version int null, frozen bool default false
(owner), created_at`.

### `parser_versions`
| Column | Type | Note |
|---|---|---|
| key | text PK | `km77@v1` |
| reader | text FK parsers | |
| version | int | unique (reader, version) |
| spec | jsonb | `ParserSpec` (contracts/parser-spec.md), validated on insert |
| spec_hash | char(12) | |
| status | text | `draft, candidate, active, degraded, superseded, rejected, retired` |
| degraded_reason | text null | |
| zero_streak | int default 0 | pages in a row with zero fields (R12) |
| author | text | `seed`, `owner`, `agent:parser_doctor` |
| change_id | uuid null | the `acq_changes` row that created it |
| created_at, activated_at | timestamptz | |

### `parser_daily`
| Column | Type | Note |
|---|---|---|
| version_key | text FK parser_versions | |
| day | date | |
| pages | int | |
| fields_total | int | |
| fields_per_page | real | |
| rows_read, rows_accepted | int | |
| pass_rate | real | rows_accepted / rows_read |
| zero_pages | int | |
| structure_hash | char(16) null | most frequent of the day |
| structure_shingles | jsonb null | shingle set of that hash (≤ 200 items) |
| structure_sim | real null | Jaccard vs the 30-day reference |
| PK (version_key, day) | | |

`site_reader_stats` stays until this table has 30 days of history; then a later spec drops it.

### `acq_changes`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| created_at | timestamptz, index | |
| author | text | `agent:parser_doctor`, `agent:rule_auditor`, `agent:extractor_tuner`, `agent:scout`, `system` (drift), `owner` |
| object_kind | text | `parser, prompt, role_model, rule, source` |
| object_key | text | `km77`, `extract_specs`, `extractor`, `plausibility.by_powertrain.HEV.max_torque.max`, `motor.es` |
| from_version | text null | `km77@v4` |
| to_version | text null | `km77@v5` |
| diff | jsonb | structured diff (JSON patch for specs/rules, unified diff text for prompts) |
| diff_hash | char(12) | for "not repeated without new evidence" |
| reason | text | trigger (drift, accuracy drop, rule cluster, gap) |
| evidence | jsonb | `{snapshots: [...], gold: [...], signals: [...], counts}` |
| gates | jsonb | `{replay: {verdict, metrics_old, metrics_new, at}, shadow: {...}, watch: {...}}` |
| metrics_before, metrics_after | jsonb | headline KPIs |
| status | text | `proposed, replay, shadow, accepted, watch, kept, rejected, abandoned, rolled_back, reverted` |
| explanation | text | one sentence with numbers, built by code |
| cost_eur | numeric(10,4) | agent + gate spend |
| reverted_by | uuid null | owner revert / automatic rollback row |
| closed_at | timestamptz null | |

Index: `unique (object_kind, object_key) where status in ('proposed','replay','shadow','accepted','watch')` — one
change per object at a time (FR-018).
Created in 0022 because drift (US4) journals parser status changes here (`author=system`, `object_kind=parser`,
`status=accepted`, no gates); the agents of US5 use the same table.

## Migration 0023 — agents, gates and overrides (US5)

### `prompt_versions`
`key text PK (extract_specs@v4), name text, version int, text text, text_hash char(12), base_key text null,
status text (candidate, active, superseded, rejected), author text, change_id uuid null, created_at, activated_at`.
Seeded with the file versions of `orchestration/prompts/extract_*.md`, `relevance.md`, `validator.md` (status active).
Chat prompts are never stored here (lever whitelist).

### `role_model_overrides`
`role text PK (extractor | validator | relevance), model text, change_id uuid, active bool, created_at`. Applied by
the gateway's model resolution only for these roles and only for models in `config/agents.yaml: allowed_models`.

### `rule_overrides`
`id uuid PK, path text (e.g. "plausibility.by_powertrain.HEV.max_torque.max"), value jsonb, status text (candidate,
active, superseded, rejected), change_id uuid, created_at, activated_at`. Unique active per path. Layered over YAML by
`infrastructure/config.py` at load (`effective = yaml ⊕ active overrides`); only paths matching
`config/agents.yaml: levers.rule_auditor.paths` with bounds `min/max/max_step_rel`.

### `acq_experiments`
`change_id uuid PK FK acq_changes, phase text (replay|shadow|watch), started_at, ends_at, corpus uuid[] (snapshot
ids, pinned), pages_old int, pages_new int, metrics_old jsonb, metrics_new jsonb, daily jsonb (per-day watch
metrics), decided_at, decision text`.

### `change_blocks`
`object_kind text, object_key text, lever text, until timestamptz null (null = forever), created_by text, reason text,
created_at`; PK `(object_kind, object_key, lever)`. "Forbid similar changes on this object" (US6).

## Migration 0024 — unverified evidence (US7)

### `evidence` (altered)
`unverified bool not null default false` — the page came from a candidate capability (010 T059): labelled
"unverified source" and counted as half an independent source towards an area's minimum.

## State machines

- **Parser version**: `draft → candidate (schema-valid) → [replay pass] → candidate(shadow) → [shadow pass] → active
  → (watch ok) active | (watch fail) superseded + previous re-activated`; `active → degraded` (drift) → `superseded`
  when a replacement is accepted; `rejected` at any gate failure; owner may `freeze` a parser (no agent change).
- **Change**: `proposed → replay → shadow → accepted → watch → kept`; any gate → `rejected` (reason journalled);
  budget/time out → `abandoned`; watch degradation → `rolled_back` (system); owner → `reverted` (any accepted state).
- **Task**: `queued → running → done | queued (retry with back-off) | dead`; `running` past `lease_until` is reclaimed.

## Validation rules (code)

- Every proposal is validated against its lever schema (`acquisition/agents/levers.py`) before an `acq_changes` row
  is written; invalid → dropped with a log line and a counter, never journalled as a change.
- No proposal may target: `sources.access`, `access_evidence`, `frozen` sources, deny-list entries, budgets
  (`agents.budgets`, `registry.discovery`, `prefetch`, `DAILY_CAP_EUR`), chat prompts, `config/*.yaml` files (no file
  writes — extended `test_no_self_change.py`).
- `change_blocks` and the one-per-object index are checked in the same transaction as the insert.
- A gold value with `flagged=true` produces no signals.
- Snapshot body is never sent to an LLM except as data inside `<untrusted_document>` to web-reader roles.
