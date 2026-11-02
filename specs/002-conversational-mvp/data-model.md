# Data Model: AutoMind Conversational MVP

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md) | **Date**: 2026-11-01

There are three layers (constitution V):

1. **Domain models**: Pydantic, framework-free (`backend/src/automind/domain`).
2. **Persistence**: PostgreSQL via SQLAlchemy 2 + Alembic.
3. **Graph state**: a compact TypedDict. LangGraph checkpoint tables are separate and owned by
   the checkpointer.

Tables marked **(demo)** already exist and are kept; the others are new.

---

## 1. Conversation

### Chat (`chats`, new)
| Field | Type | Rules |
|---|---|---|
| id | UUID | Also the LangGraph `thread_id` |
| title | str | Generated from the first message (≤60 chars), editable |
| language | str | ISO 639-1, last detected |
| created_at / updated_at | timestamptz | |

### ChatMessage (`chat_messages`, demo, extended)
`id, chat_id, turn_id, role (user|assistant), text, blocks jsonb, created_at`.

### Turn (`turns`, new)
| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| chat_id | UUID | |
| seq | int | Monotonic per chat |
| user_message_id | UUID | |
| request_kind | enum | compare, single, follow_up_question, weights_change, correction, general_question, confirm_yes, confirm_no, chitchat |
| action | enum | ANSWER_GENERAL, ASK, CONFIRM_VARIANTS, CONFIRM_COST, RESEARCH, ANSWER_FROM_CONTEXT, REPORT |
| case_version_before / after | int | |
| fingerprint | str | Hash of cars + criteria + weights + persona + settings; used by the no-repeat rule (FR-004) |
| cost_estimate_eur | numeric? | |
| usage | jsonb | `{llm_calls, input_tokens, output_tokens, search_calls, cost_eur}` across all roles (FR-042) |
| limits_reached | str[] | |
| status | enum | RUNNING, WAITING_CONFIRMATION, DONE, CANCELLED, FAILED |
| created_at / finished_at | timestamptz | |

### TurnEvent (`turn_events`, new)
`chat_id, seq (bigint, monotonic per chat), turn_id, type, payload jsonb, created_at`, with
primary key `(chat_id, seq)`. Used for WebSocket replay (R13).

## 2. Case file

### CaseFile (domain model; table `case_files(chat_id, version, data jsonb, changed_by, change_log jsonb, created_at)`, PK `(chat_id, version)`)

```text
CaseFile
├── persona: EXPERT | PERFORMANCE | BUYER | UNKNOWN            (FR-002, FR-005a)
├── persona_source: INFERRED | ASKED | USER_EDIT
├── profile: { age?: int, experience?: str }
├── usage: set[CITY, MOTORWAY, MOUNTAINS, OFFROAD, TRACK, FAMILY]
├── budget: { max_eur?: int, note?: str }
├── annual_km: int = 15000                                      (TCO default)
├── rates_override: { fuel_eur_l?, electricity_eur_kwh?, labour_eur_h? }
├── depth: QUICK | STANDARD | DEEP = STANDARD
├── priorities: list[{ criterion: CriterionKey, strength: LOW|MEDIUM|HIGH, source: USER|PERSONA }]
├── weights: dict[CriterionKey, float]   (derived; normalized to 100; user may override)
├── weights_overridden: bool
├── unmapped_wishes: list[str]                                  (FR-028)
├── cars: list[CaseCar]  (max 3; key "car#1".. stable within chat)
├── race_settings: { surface: DRY|WET, extra_load_kg: 0–500, temperature_c?, altitude_m? } | null   (FR-038)
├── prediction: { winner_key: "car#N" } | null                                                    (US6)
├── pending: { kind: QUESTIONS | CONFIRM_VARIANTS | CONFIRM_COST, items: [...] } | null
└── shown: list[{ turn_seq, fingerprint, blocks: [types] }]    (FR-004)

CaseCar
├── key: "car#N"
├── request_text: str                (what the user said)
├── condition: NEW | USED | UNKNOWN
├── year?: int, age_years?: int, mileage_km?: int
├── constraints: { generation_hint?, fuel_hint?, body_hint?, trim_hint?, url? }
├── variant_id?: UUID                (resolved)
├── resolution: UNRESOLVED | PROPOSED | CONFIRMED | AUTO_OK
└── alternatives: list[UUID | VariantIdentity]
```

**Validation rules**:
- ≤3 cars (more → ASK).
- `age_years` and `year` are consistent: `year = current_year − age` ± 1.
- Weights are ≥0 and sum to 100 ±0.01.
- Criterion keys must exist in the dictionary version.

**apply(case, delta) → (case', change_log)** is pure:
- The latest statement wins.
- `replace_car` keeps the key and resets `variant_id` and `resolution`.
- Priorities recompute the weights unless `weights_overridden`.
- A user PATCH sets `changed_by=user`.

### CaseDelta (domain model; LLM structured output, validated)
`set_persona?, set_profile?, set_usage?, set_budget?, set_annual_km?, set_depth?,
add_priorities[], remove_priorities[], add_cars[], replace_cars[{target_key, request_text,
condition, year?, age_years?, mileage_km?, constraints}], remove_cars[target_key],
set_car_context[{target_key, ...}], unmapped_wishes[], set_race_settings?, set_prediction?,
set_rates_override?`.

### Glossary (spec wording ↔ code enums)
| Spec | Code |
|---|---|
| everyday or family buyer | `BUYER` (reporter `buyer`) |
| performance enthusiast | `PERFORMANCE` (reporter `performance`) |
| expert | `EXPERT` (reporter `expert`) |
| unknown persona, "balanced default layout" | `UNKNOWN` (reporter `balanced`) |
| single-car profile report | comparison with 1 car: `ranked=false`, no winner, no race |

## 3. Criteria

### Criterion (config `config/criteria.yaml`, loaded into the domain; version recorded on results)
`key, label, definition, inputs[], scale {kind: linear|categorical|composite|review_balance, lo,
hi, map, parts[]}, min_data rule, persona_default_weight{EXPERT, PERFORMANCE, BUYER, UNKNOWN}`.
Keys are as in research R7.

### CriteriaScore (computed, not stored separately; embedded in report blocks and turns)
`criteria_version, per car: {total|null, ranked: bool, coverage, parts: {key: {score|null,
weight, inputs: [...], insufficient: bool}}}, winner`.

## 4. Vehicles and evidence (demo tables, extended)

| Table | Status | Changes |
|---|---|---|
| `vehicle_variants` | demo | + `generation_years_from`, `generation_years_to`, `class` (small/compact/mid_large/premium_suv_4x4), `segment`, `brand_positioning` (via sourced claim); `canonical_key` normalized via aliases; de-dup on insert (R6) |
| `documents` | demo | + `content_sha256` unique (store once) |
| `evidence` | demo | + `snippet_only` bool |
| `claims` | demo | + `area`; `attribute` registry extended (practicality, Tier 2 engineering, price class, segment, euro_ncap, ground_clearance, low_range, tyre_size, fiscal_hp) |
| `spec_values` | demo | unchanged shape (selected value per variant × attribute) |
| `research_runs` | demo | keyed by `(variant_id, area)`; + `rounds_used`, `minimum_met` bool |

### New per-variant research results
| Table | Fields |
|---|---|
| `maintenance_items` | variant_id, interval_km?, interval_months?, item, cost_eur?, cost_basis, evidence_ids[], age_window? |
| `review_items` | variant_id, polarity (PRO/CON), tag (comfort, handling, quality, practicality, noise, reliability, value, other), reviewer (EXPERT/OWNER), text, evidence_id, recurring bool (computed) |
| `issues` | variant_id, component, description, age_from?, age_to?, mileage_from?, mileage_to?, severity (LOW/MEDIUM/HIGH, from wording rules), recurrence (RECURRING/ISOLATED, ≥2 domains), evidence_ids[] |
| `reliability_stats` | variant_id, source, metric, value, year, evidence_id |
| `manufacturer_facts` | make, fact_type (history, key_model, market_position), text, evidence_id, retrieved_at |

### ResearchJob (`research_jobs`, new; R14)
`id, chat_id, turn_id, variant_id, area, round, status (PENDING|RUNNING|DONE|FAILED|SKIPPED),
attempts, error?, docs, accepted, rejected, started_at, finished_at`.

## 5. Computations (deterministic outputs)

### TcoEstimate (`tco_estimates`, new; stored per turn for reproducibility)
`id, turn_id, variant_id, condition, age_years?, mileage_km?, annual_km, rates jsonb, items:
[{kind: MAINTENANCE|ENERGY|TYRES|ROAD_TAX|BIG_TICKET|BASE_RESERVE, label, annual_eur?,
five_year_eur?, basis: SOURCED|ASSUMPTION, inputs, evidence_ids[]}], annual_total,
five_year_total, rules_version`.

### Simulation (`simulations`, new; demo computed it on the fly)
`id, turn_id, model_version, settings, prediction?, inputs, assumptions, results, input_hash`.

### Usage (`llm_calls` demo + `search_calls` new)
`llm_calls`: + `turn_id`, `cost_eur`. `search_calls`: `turn_id, provider, kind (search|extract),
credits, cost_eur, created_at`.

## 6. Graph state (orchestration only)

```python
class TurnState(TypedDict, total=False):
    chat_id: str
    turn_id: str
    case_version: int                      # authoritative case lives in DB
    user_text: str
    interpretation: dict                   # compact validated Interpretation
    action: str                            # policy result
    pending: dict | None                   # mirrors case.pending for interrupts
    research_plan: dict                    # cars × areas × rounds (ids only)
    job_results: Annotated[list[dict], operator.add]   # parallel workers append
    reply_text: str
    blocks: list[dict]
    notices: Annotated[list[dict], operator.add]
```

Only the policy node writes `action`; only the composer writes `reply_text` and `blocks`.
Workers append to `job_results` and `notices` only (constitution VI).

## 7. Lifecycles

**Turn**:
```text
RUNNING → DONE
RUNNING → WAITING_CONFIRMATION → RUNNING → DONE
any → CANCELLED | FAILED
```

**CaseCar.resolution**:
```text
UNRESOLVED → PROPOSED → CONFIRMED   (or AUTO_OK when unambiguous + cached + fresh)
any → UNRESOLVED                    on replace_car
```

**ResearchJob**:
```text
PENDING → RUNNING → DONE | FAILED
PENDING → SKIPPED                   (cache fresh / cancelled)
```
