# Data Model: The User's Profile Drives the Assessment

## Case file (JSON in `case_files`, no migration; upgraded on read)

| Field | Type | Rules |
|---|---|---|
| `basis` | `dict[field, "STATED" \| "INFERRED" \| "ASSUMED"]` | See below |
| `profile.evidence` | `dict[field, str]` | User's words. Required for STATED and INFERRED fields set by the interpreter; must occur in a user message of the chat |
| `ownership_years` | `int \| None`, 1–20 | None → persona default (ASSUMED) |
| `annual_km` | `int` | Basis replaces `annual_km_stated` (kept read-only for old rows) |
| `budget.intent` | `NEW \| USED \| EITHER \| UNKNOWN` | Existing; it is the profile's "new or used" |
| `running_cost_limit` | existing | Shown as the monthly spending limit (EUR/month). Basis key `monthly_limit` |
| `weight_adjustments` | `dict[criterion, float]` | Manual points on top of the automatic weights; may be negative; a final weight of 0 means "excluded by you" |
| `weights`, `weights_overridden` | deprecated | Converted on read: `weight_adjustments = weights − automatic`; then ignored |
| `hops` | graph state, not the case | Reset per turn |

`basis` keys:
- persona;
- ownership_years;
- condition;
- annual_km;
- budget;
- monthly_limit;
- family;
- driving_style;
- region;
- usage.

Precedence: STATED > INFERRED > ASSUMED. A lower basis never overwrites a higher one. A panel edit is STATED.

Upgrade of old rows:
- `persona_source == USER_EDIT` → `basis.persona = STATED`.
- `annual_km_stated` → STATED.
- A profile field with evidence → INFERRED.
- Everything else → ASSUMED.

## WeightBreakdown (pure, `domain/weights.py`)

```text
WeightBreakdown
  criteria: dict[criterion, WeightLine]
  capped: list[criterion]            # criteria hit by the cap
  version: rules_version
WeightLine
  base: float                        # persona default
  contributions: list[(reason_code, points)]   # profile rules, priorities
  manual: float                      # from weight_adjustments
  final: float                       # normalised, sum = 100
```

`reason_code` is a rule id (`family.FAMILY`, `annual_km.>25000`, `priority.safety`). The UI localizes it from `report_text`.

## profile_rules.yaml (config)

```yaml
version: 1
cap: 50
rules:
  family:        {FAMILY: {practicality: 10, safety: 8, comfort: 5}}
  driving_style: {SPORTY: {performance: 8, driving_fun: 8}, CALM: {comfort: 5, efficiency: 5}}
  usage:         {MOUNTAINS: {performance: 5, traction_all_weather: 6}, CITY: {efficiency: 6, practicality: 3},
                  MOTORWAY: {comfort: 6, efficiency: 4}, TRACK: {performance: 10, driving_fun: 8}, OFFROAD: {offroad_mountain: 12}}
  climate:       {COLD: {traction_all_weather: 5}, HOT: {comfort: 3}}
  annual_km:     {">25000": {efficiency: 8, ownership_cost: 5}, "<8000": {purchase_price: 5}}
  ownership_years: {">=8": {reliability: 8, ownership_cost: 5}, "<=3": {purchase_price: 5}}
  condition:     {USED: {reliability: 6}}
```

Validation:
- criteria must exist in criteria.yaml;
- bands are `<N`, `<=N`, `>N`, `>=N`;
- unknown fields fail at load.

## profile_defaults.yaml (config)

```yaml
personas:
  PERFORMANCE: {ownership_years: 4, annual_km: 12000, condition: NEW}
  BUYER:       {ownership_years: 7, annual_km: 15000, condition: NEW}
  EXPERT:      {ownership_years: 5, annual_km: 15000, condition: NEW}
  UNKNOWN:     {ownership_years: 5, annual_km: 15000, condition: NEW}
probe:          # values tried by questions-by-value
  annual_km: [8000, 15000, 30000]
  ownership_years: [3, 6, 10]
  persona: [PERFORMANCE, BUYER]
```

## learned_sources (table, migration 0010)

| Column | Type | Notes |
|---|---|---|
| id | uuid pk | |
| domain | text | Registrable host, lower case |
| area | text | Research area |
| market | text | ES, DE, … |
| source_type | text | From `classify_source`; never MANUFACTURER unless `is_official` |
| accepted_runs | int | Runs where a selected value came from this domain |
| misses | int | Consecutive runs where it was searched for the area but gave nothing accepted |
| first_seen, last_seen | timestamptz | |

The pair `unique(domain, area, market)` is unique.

Active when all of these hold:
- `accepted_runs >= min_runs`;
- `misses < max_misses`;
- not denied;
- not a configured favourite for that area.

## search_cache (existing table)

- `+ empty boolean not null default false`.
- An empty row expires after `empty_result_ttl_hours`.

## Policy and fingerprint

- `fingerprint_data(case, data_version)` and `fingerprint_params(case, language)` are both sha256 over sorted JSON.
- The stored last turn keeps both (`turns.fingerprint` becomes `"<data>:<params>"`; old single values count as "both changed").
- Action enum: `+ RESCORE`, `+ SELECT_CANDIDATES`.
- A decision reason has a stable code: `params_changed`, `data_stale`, `nothing_new`, `hops_exceeded`.

## Findings and insights (codes)

| Code | Payload | Origin |
|---|---|---|
| `OVER_BUDGET` | car_id, price_eur, budget_eur | FR-017 |
| `OVER_MONTHLY` | car_id, monthly_eur, limit_eur | FR-017 |
| `OTHER_PROFILE_WINS` | persona, car_id | FR-018 |
| `USED_DATA_MISSING` | car_id, missing: [price_used, wear] | FR-019 |
| `TCO_PERIOD` | years, basis | FR-016 (shown on the TCO block) |
