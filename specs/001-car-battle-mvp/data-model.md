# Data Model: Ultimate Car Battle (AutoMind MVP)

**Feature**: [spec.md](./spec.md) | **Research**: [research.md](./research.md) | **Date**: 2026-11-01

There are three layers, and each must not leak into the others (constitution V):

1. **Domain models**: Pydantic v2, framework-free (`backend/src/automind/domain`).
2. **Persistence**: PostgreSQL tables via SQLAlchemy and Alembic (`infrastructure/db`).
   LangGraph checkpoint tables are separate and owned by the checkpointer.
3. **Graph state**: a `TypedDict` that holds IDs and compact summaries only (see the end of this
   document).

Conventions: UUIDv7 primary keys; `created_at` and `updated_at` as `timestamptz`. Physical
quantities are stored in canonical SI units as `NUMERIC` with a `unit` column kept for audit.
Enum values are stored as text.

---

## 1. Enumerations

| Enum | Values |
|---|---|
| `Powertrain` | `ICE`, `BEV`, `HEV`, `PHEV`, `MHEV` (MHEV is treated as ICE in simulation) |
| `Drivetrain` | `FWD`, `RWD`, `AWD` |
| `TransmissionType` | `MANUAL`, `AUTOMATIC`, `DCT`, `CVT`, `SINGLE_SPEED` |
| `BodyClass` | `HATCHBACK`, `SEDAN`, `WAGON`, `COUPE`, `CONVERTIBLE`, `SUV`, `MPV`, `PICKUP` |
| `SourceType` (authority order, high → low) | `MANUFACTURER`, `INSTRUMENTED_TEST`, `PUBLICATION`, `ENCYCLOPEDIA`, `SPEC_DATABASE` |
| `Provenance` | `MANUFACTURER_CLAIM`, `MEASURED`, `SOURCED_FACT`, `DERIVED`, `SIMULATED_ESTIMATE`, `ASSUMPTION` |
| `Confidence` | `HIGH`, `MEDIUM`, `LOW` |
| `WeightDefinition` | `EU_WITH_DRIVER`, `DIN_WITHOUT_DRIVER`, `UNKNOWN` |
| `ResearchState` | `CREATED`, `PLANNING`, `AWAITING_APPROVAL`, `RUNNING`, `VERIFYING`, `ANALYZING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| `TaskStatus` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `RETRYING`, `SKIPPED` |
| `ResearchCategory` | `TECHNICAL_SPECS`, `MEASURED_PERFORMANCE`, `TECHNICAL_ISSUES`, `MARKET` (MARKET disabled in the MVP, FR-039) |
| `ConflictStatus` | `RESOLVED`, `UNRESOLVED` |
| `IssueRecurrence` | `RECURRING`, `ISOLATED` |
| `CatalogFreshness` | `FRESH`, `STALE` |
| `Surface` | `DRY`, `WET` |

## 2. Specification attributes (closed registry)

`SpecAttribute` is a registry. Each entry has a key, tier, canonical unit, value kind (numeric or
categorical), and conflict tolerance. It drives research prompts, completeness checks, and
conflict detection.

| Tier | Keys (canonical unit) |
|---|---|
| 1 | `max_power` (kW, + `max_power_rpm`), `max_torque` (N·m, + `max_torque_rpm_from`/`_to`), `curb_mass` (kg, + `weight_definition`), `drivetrain`, `transmission_type`, `gear_count`, `claimed_0_100` (s), `claimed_top_speed` (km/h), `engine_type`, `displacement` (cm³), `fuel_type`; EV/PHEV: `battery_capacity_usable` (kWh), `battery_capacity_gross` (kWh), `motor_count`, `motor_power` (kW per motor), `system_power` (kW, hybrids) |
| 2 | `engine_code`, `engine_layout`, `cylinder_count`, `aspiration`, `bore` (mm), `stroke` (mm), `compression_ratio`, `redline` (rpm), `gear_ratios` (list), `final_drive`, `weight_distribution_front` (%), `length`/`width`/`height`/`wheelbase` (mm), `tyre_size_front`/`_rear`, `brakes_front`/`_rear`, `suspension_front`/`_rear`, `drag_coefficient`, `frontal_area` (m²), `platform` |
| 3 | `measured_0_100` (s), `measured_0_200` (s), `measured_400m` (s), `measured_400m_speed` (km/h), each with `test_source` |

Tolerances (rules v1.0): power and torque ±2%; mass and dimensions ±3%; `claimed_0_100` ±0.2 s;
categorical values must match exactly.

## 3. Domain entities

### VehicleVariant (catalog identity), table `vehicle_variants`

| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| make | str | Required, normalized case |
| model | str | Required |
| generation_code | str? | e.g. "Mk8", "CN7" |
| generation_years | int range? | |
| variant_name | str | e.g. "GTI Clubsport 2.0 TSI 300 PS DSG" |
| powertrain | Powertrain | Required |
| model_year_from / model_year_to | int / int? | `from ≤ to` |
| market | str (ISO 3166-1) | Default `ES` |
| body_class | BodyClass? | Used for simulation assumptions |
| canonical_key | str, unique | Normalized `(make, model, generation_code, variant_name, powertrain, model_year_from, market)` |
| last_researched_at | timestamptz? | Drives freshness |
| freshness (computed) | CatalogFreshness | `STALE` when older than `CATALOG_FRESHNESS_DAYS` (90) |

`vehicles` (make and model) and `vehicle_generations` from `sec.md` are kept as normalized
parent tables: `vehicle_variants.generation_id → vehicle_generations.id → vehicles.id`.

### Evidence, table `evidence`

| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| url | str | Required |
| source_name | str | e.g. "Volkswagen Newsroom" |
| source_domain | str | Registrable domain; used to decide whether sources are independent |
| source_type | SourceType | From the source registry |
| retrieved_at | timestamptz | Required |
| artifact_id | UUID → research_artifacts | Full stored document text |
| language | str? | |
| snippet_only | bool | true when only a search snippet was available (source marked `snippet_only` in the registry, or fetch not allowed); drives LOW confidence |
| variant_id | UUID → vehicle_variants | The variant this evidence refers to |

### Claim, table `claims`

| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| research_id | UUID | |
| variant_id | UUID | |
| evidence_id | UUID | Required |
| attribute | SpecAttribute key | Must exist in the registry |
| raw_value / raw_unit | str / str? | As written in the source |
| normalized_value | NUMERIC? / str? | Canonical unit; categorical as text |
| qualifiers | jsonb | e.g. `{rpm: 6500}`, `{weight_definition: "DIN"}` |
| excerpt | str | **MUST** be present in the artifact text (excerpt validator) |
| scope | `VARIANT`, `GENERATION`, `ENGINE` | What the source states the value for; `GENERATION`/`ENGINE` scope means indirect evidence (LOW confidence) |
| provenance | Provenance | Assigned by `assign_provenance(source_type, attribute)`: `MANUFACTURER` → `MANUFACTURER_CLAIM`; `INSTRUMENTED_TEST` and Tier 3 attribute → `MEASURED`; otherwise `SOURCED_FACT` |
| status | `ACCEPTED`, `REJECTED_VARIANT_MISMATCH`, `REJECTED_UNSUPPORTED`, `REJECTED_UNIT` | Set by verification |
| rejection_reason | str? | |

### SpecValue (resolved value per variant), table `vehicle_specs`

| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| variant_id | UUID | |
| attribute | key | Unique per `(variant_id, attribute, research_id)` |
| research_id | UUID | The research that produced it (catalog reuse references the original) |
| value | NUMERIC? / str? | `NULL` together with `available=false` means unavailable (FR-013) |
| unit | str? | Canonical |
| available | bool | |
| provenance | Provenance | |
| confidence | Confidence | Computed by `confidence_rules v1.0` |
| confidence_rule | str | e.g. `HIGH:MANUFACTURER`, `HIGH:2_INDEPENDENT_AGREE`, `MEDIUM:SINGLE_SOURCE`, `LOW:UNRESOLVED_CONFLICT` |
| selected_claim_id | UUID? | |
| conflict_id | UUID? | |
| derived_from | jsonb? | For `DERIVED` values (e.g. DIN mass + 75 kg) |

### Conflict, table `conflicts`

| Field | Type | Rules |
|---|---|---|
| id, research_id, variant_id, attribute | | |
| claim_ids | UUID[] | At least 2 |
| status | ConflictStatus | |
| resolution_rule | str? | `AUTHORITY_ORDER`, `MAJORITY_SAME_RANK`; NULL if unresolved |
| selected_claim_id | UUID? | |
| followup_rounds_used | int | ≤ `max_followup_rounds` |

### TechnicalIssue, table `technical_issues`

`id, research_id, variant_id, component (str), description (str), recurrence (IssueRecurrence),
evidence_ids (UUID[] ≥1)`. The rule is `RECURRING` when there are at least 2 distinct source
domains. Opinions are filtered out by an extraction schema that requires a component.

### Research, table `researches`

| Field | Type | Rules |
|---|---|---|
| id | UUID | Also the LangGraph `thread_id` |
| question | str? | |
| market | str | Default `ES` |
| state | ResearchState | Transitions below |
| categories | ResearchCategory[] | Default: technical specs, measured performance, technical issues |
| limits | jsonb | `{max_llm_calls: 150, max_followup_rounds: 2, max_concurrency: 6, request_timeout_s: 30}`; `request_timeout_s` applies to every external call (LLM, search, extract); direct page fetches use `min(request_timeout_s, 15)` |
| cancel_requested | bool | |
| failure_reason | str? | |
| limits_reached | str[] | e.g. `["max_llm_calls"]` |
| created_at / started_at / completed_at | timestamptz | |

### ResearchVehicle, table `research_vehicles`

`research_id, position (1–4), input_text, input_model_year?, candidate_variant_ids (UUID[]),
selected_variant_id?, ambiguity (NONE | AMBIGUOUS | UNIDENTIFIED), data_mode (RESEARCH | REUSE)`.
Validation: 2–4 rows per research (FR-001). Before approval, every row needs a
`selected_variant_id` (FR-004). `REUSE` is allowed only when the variant is `FRESH` (FR-040). A
duplicate `selected_variant_id` within one research produces a warning (edge case).

### ResearchPlan, a snapshot in `researches.plan` (jsonb, versioned)

`version, vehicles[{position, variant summary, alternatives[], ambiguity, catalog_status (NEW |
FRESH | STALE), data_mode}], categories[], tasks[{category, vehicle_position}],
planned_source_types[], estimated_task_count, ambiguities[], approved_at?, rejected_at?`

### ResearchTask, table `research_tasks`

`id, research_id, vehicle_position, category, status (TaskStatus), attempt (int), started_at,
finished_at, error?, followup_round (0 = initial)`. One row per Send branch; it is updated by the
worker node through the repository, never by direct writes to graph state.

### ResearchArtifact, table `research_artifacts`

`id, research_id, kind (DOCUMENT_TEXT | REPORT | SIM_TIMESERIES), sha256, path, size_bytes,
media_type, created_at`. Files live under `data/artifacts/`.

### ResearchEvent, table `research_events`

`research_id, seq (bigint, monotonic per research), type, payload (jsonb DTO), created_at`, with
primary key `(research_id, seq)`. This is the source for SSE replay.

### LLMCall, table `llm_calls`

`id, research_id?, role, provider, model, input_tokens, output_tokens, latency_ms,
estimated_cost_eur, status, created_at`.

### Comparison, table `comparisons`

`id, research_id, variant_ids[], metrics (jsonb: per variant {power_to_weight_kw_per_t,
torque_to_weight_nm_per_t, weight_to_power_kg_per_kw, specific_output_kw_per_l?}), rankings
(jsonb: per metric ordered variant_ids + excluded[{variant_id, reason}]), rules_version,
created_at`. All metrics have provenance `DERIVED` with input SpecValue IDs.

### Simulation, table `simulations`

| Field | Type | Rules |
|---|---|---|
| id | UUID | |
| research_id | UUID? | Optional; runs can also be started from the catalog |
| model_version | str | `dragrace-0.1.0` |
| settings | jsonb | `{surface: DRY|WET, extra_load_kg: 0–500, temperature_c: −20–50, altitude_m: 0–3000}` |
| prediction | UUID[]? | User-predicted finishing order (FR-041) |
| inputs | jsonb | Per vehicle: the exact input values, with SpecValue IDs |
| assumptions | jsonb | Per vehicle: `[{name, value, unit, reason}]`, provenance `ASSUMPTION` |
| results | jsonb | Per vehicle: `t_0_100, t_0_200 | null, t_400m, v_400m, finish_rank, notes[]`; `excluded[{variant_id, reason}]` |
| timeseries_artifact_id | UUID | Arrays of t, v, s, a per vehicle (sampled every 0.05 s) |
| input_hash | str | sha256 of `(model_version, inputs, assumptions, settings)`; identical hash gives identical results (SC-008) |

### Report, artifact of kind REPORT plus `researches.report_artifact_id`

This is an immutable JSON document assembled when the research completes (FR-029, FR-030). It
contains variants, specs by tier, comparison, default simulation, issues, evidence index,
conflicts, confidence summary, `limits_reached`, and usage totals. Reopening it reads the stored
artifact, so the content never changes.

## 4. Research state machine (FR-031)

```text
CREATED ──start──▶ PLANNING ──plan ready──▶ AWAITING_APPROVAL
AWAITING_APPROVAL ──approve──▶ RUNNING
AWAITING_APPROVAL ──edit──▶ PLANNING               (re-plan with user choices, plan_version+1)
AWAITING_APPROVAL ──reject──▶ CANCELLED           (no research tasks run)
RUNNING ──all tasks done──▶ VERIFYING
VERIFYING ──follow-up needed & rounds left──▶ RUNNING (follow-up tasks only)
VERIFYING ──done──▶ ANALYZING ──report stored──▶ COMPLETED
any non-terminal ──cancel──▶ CANCELLED
any non-terminal ──unrecoverable error──▶ FAILED
```

The transitions are enforced by `domain.research.transition(state, event)`, a pure function. Any
other transition raises `InvalidTransition`. Failure of a single task is **not** a transition to
`FAILED` (FR-007, SC-012).

## 5. Graph state (orchestration only)

```python
class ResearchGraphState(TypedDict):
    research_id: str
    vehicle_positions: list[int]
    plan_version: int
    approved: bool
    task_results: Annotated[list[TaskResultRef], operator.add]   # reducer: append-only
    followup_round: int
    followup_requests: list[FollowupRequest]                      # written only by verify node
    verification_summary_id: str | None
    comparison_id: str | None
    simulation_id: str | None
    report_artifact_id: str | None
    limits_reached: Annotated[list[str], merge_unique]

class TaskResultRef(TypedDict):          # compact: no documents, no claims
    task_id: str
    vehicle_position: int
    category: str
    status: str
    claim_count: int
    artifact_ids: list[str]
```

Parallel workers write only to `task_results` (append reducer) and `limits_reached` (union
reducer). Every other field has a single writer node, so there are no conflicting parallel
updates (constitution VI).
