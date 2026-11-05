# Data Model: Spec 010

All tables in PostgreSQL next to the existing ones. Timestamps are `timestamptz`. JSONB where noted.

## Migration 0014 — observation

### `llm_calls` (altered)
| Column | Type | Note |
|---|---|---|
| primary_model | text null | the role's configured model |
| fallback | bool default false | `model != primary_model` |
| prompt_name | text null | e.g. `interpreter` |
| prompt_version | text null | e.g. `v3` (from the header comment) |
| prompt_hash | text null | sha256[:12] of the system text |

### `turn_outcomes`
| Column | Type | Note |
|---|---|---|
| turn_id | uuid PK, FK turns (cascade) | |
| chat_id | uuid FK chats (cascade), index | |
| created_at | timestamptz, index | |
| request_kind | text | copied from the turn |
| action | text null | REPORT, ASK, … |
| language | text null | |
| persona | text null | |
| path | text[] | node names in order |
| status | text | DONE, FAILED, CANCELLED, WAITING |
| duration_ms | int null | |
| cost_eur | numeric(10,4) | |
| relation_next | text null | relation of the next user message |
| failure_classes | text[] | `not_understood, wrong_car, no_data, wrong_data, bad_text, process_failure, too_costly` |
| signals | jsonb | `{thanks:1, rephrase:1, guard_removed:2, nodata:[{car,area}], ...}` |
| score | real | 0–1, recomputed when signals change |
| settings_version | text | hash of models.yaml + prompt hashes in use |

Rules: one row per turn; created in `_done/_fail/cancel`; patched by the next turn (relation), by feedback on its message, by challenge results. `score` recomputed by `domain/outcome.score` on every patch.

### `feedback`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| created_at | timestamptz, index | |
| chat_id | uuid FK chats (cascade) | |
| turn_id | uuid null FK turns | |
| message_id | uuid null | assistant message |
| kind | text | `rating, wrong_value, bad_source, complaint, rephrase, correction` |
| rating | smallint null | 1–5 |
| variant_id | text null | |
| attribute | text null | |
| area | text null | kind of data |
| domain | text null | source domain |
| url | text null | |
| claim_id | uuid null | |
| text | text null | ≤ 1000 chars |
| outcome | text null | challenge outcome |

## Migration 0015 — insight

### `issues`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| fingerprint | text unique | sha1 of key |
| component | text | dialogue, parser, relevance, check, nodata, model, seeded |
| klass | text | failure class or rule |
| key | text | full key, e.g. `dialogue/not_understood/compare/ru` |
| title | text | |
| count_total | int | |
| count_7d | int | |
| first_seen, last_seen | timestamptz | |
| examples | jsonb | `[{chat_id, turn_id, quote, url, claim_id}]` ≤ 10 |
| diagnosis | jsonb null | `{summary, likely_cause, fix: {kind: code|config, files[], config_file, config_key, suggested_value, direction}, verify}` |
| impact | real | failing turns 7d × class severity + 2 × chats affected; recomputed each run |
| diagnosed_at | timestamptz null | |
| status | text | `open, acknowledged, fixed, wontfix, regression` |
| fixed_at | timestamptz null | |
| fixed_ref | text null | commit or PR |
| source | text | `auto` or `seed:009` |

Transitions: open → acknowledged → fixed / wontfix (owner); fixed → regression (system, when `count` since `fixed_at` ≥ threshold); regression → fixed (owner). wontfix never reopens.

### `insight_runs`
`id, started_at, finished_at, kind (daily|early), groups int, issues_new int, diagnosed int, cost_eur numeric, error text null`.

## Migration 0016 — registry

### `sources`
| Column | Type | Note |
|---|---|---|
| domain | text PK | registrable domain |
| source_type | text | MANUFACTURER, SPEC_DB, PUBLICATION, INSTRUMENTED_TEST, VALUER, FORUM, OTHER |
| family | text | mirror family (default = domain) |
| markets | text[] | |
| languages | text[] | |
| access | text | `ok, robots_partial, robots_blocked, terms_forbid, classifieds, paywall, js_only, dead, unknown` |
| access_evidence | jsonb | `{robots_paths[], clause, url, rule}` |
| checked_at | timestamptz null | |
| next_check_at | timestamptz null | 90/180 days |
| reader | text null | site reader name (parsers stay in `site_readers.yaml`) |
| frozen | bool default false | owner-only |
| note | text null | |

### `capabilities`
| Column | Type | Note |
|---|---|---|
| id | uuid PK | |
| domain | text FK sources | |
| area | text | kind of data |
| market | text | ES, DE, EN, FR, IT, … or `ANY` |
| status | text | `discovered, candidate, active, degraded, retired, blocked` |
| priority_seed | int null | favourite priority from YAML (behaviour parity) |
| attempts, accepted | real | decayed counts |
| rejected | jsonb | `{reason: decayed count}` |
| right_w, wrong_w | real | decayed truth weights |
| robots_refusals, junk | real | decayed |
| cost_eur | real | decayed spend |
| score, acc_mean, acc_lb, yield | real | cached, recomputed by review |
| decayed_at | timestamptz | last decay applied |
| status_since | timestamptz | |
| last_used | timestamptz null | |
| unique (domain, area, market) | | |

### `registry_attempts`
Append-only: `id, created_at, capability_id, job_id, variant_id, url, outcome (accepted|rejected|robots|junk|empty|error), reason, values int, cost_eur`. Monthly retention 180 days (retention loop).

### `truth_signals`
`id, created_at, capability_id null, variant_id, attribute, claim_id null, kind (challenge|bad_source|replacement|agreement|gold), verdict (right|wrong), weight real, blame (source|parser|extractor|relevance|check|fusion), details jsonb`.

### `registry_changes`
`id, created_at, author (system|owner), capability_id null, domain, field (status|priority|access|frozen|added), before jsonb, after jsonb, reason text, evidence jsonb, reverted_by uuid null, held bool default false (would-be change blocked by frozen/limit)`.

### `registry_runs`
`id, started_at, finished_at, kind (daily|early), changes int, discovery_queries int, cost_eur, error`.

## Validation rules (code, `acquisition/registry/domain/limits.py`)

- a capability of a source with `access ∈ {classifieds, terms_forbid, robots_blocked}` or on the deny-list is always `blocked`; the system never writes another status for it;
- `frozen` sources: no system change, the change is journalled with `held=true`;
- a change reverted by the owner is not re-applied for that capability until a newer signal or attempt exists (`created_at > revert time`);
- loop health (last success, failures in a row) is kept in memory and exported to Prometheus; no table;
- discovery spend per day ≤ `registry.discovery_eur_per_day`; insight spend ≤ `insight.budget_eur`; both counted in `DAILY_CAP_EUR`;
- no code path writes YAML config or prompts (checked by a test scanning the packages for file writes).
