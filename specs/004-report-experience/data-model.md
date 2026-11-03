# Data Model: Report Experience

Changes on top of 002/003. One Alembic migration `0007_report_experience`.

## Changed tables

| Table | Change | Notes |
|---|---|---|
| `vehicle_variants` | + `transmission varchar(16)` (`manual`, `automatic`, `dct`, `cvt`, `e-cvt`, `single`), + `drive varchar(4)` (`FWD`, `RWD`, `AWD`) | FR-028; filled by the resolver, or from unanimous accepted claims; null = unknown |
| `vehicle_variants` (level) | + `trim varchar(64)`, + `trim_level varchar(4)` (`BASE`, `MID`, `TOP`), + `price_eur numeric(10,0)` (official, null = unknown) | FR-029 |
| `manufacturer_facts` | `fact_type` gains `MARKET_SHARE`, `FINANCIAL`, `RELIABILITY_REPUTATION`, `NETWORK_ES`; + `value_num`, `year` | FR-006 |
| `claims` | `reject_rule` values from the sense layer (`sense.<attribute>.<rule>`) | FR-027 metrics |

## New tables

### `value_retention` (shared)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| variant_id | FK vehicle_variants | |
| evidence_id | FK evidence null | null = labelled estimate from the depreciation curve |
| years | smallint | 3 or 5 (others allowed) |
| share | numeric(4,3) null | value left as a share of the new price |
| eur | numeric(10,0) null | or an amount |
| market | varchar(4) | ES/GB/DE/US |
| quoted_on | date null | |
| basis | varchar(12) | `SOURCED` / `ASSUMPTION` |
| excerpt | text | |

### `report_ratings` (chat-scoped)

`message_id` PK, `chat_id`, `rating smallint 1–5`, `note text`, `created_at`. Deleted with the chat.

### `value_challenges` (chat-scoped)

`id`, `chat_id`, `turn_id`, `variant_id`, `attribute` or `claim_id`, `user_text`, `outcome`
(`CONFIRMED`, `CORRECTED`, `REMOVED`, `UNRESOLVED`), `details jsonb`, `created_at`.

## Case file (JSON)

```text
profile:
  age, experience (existing) + family: SINGLE|COUPLE|FAMILY|null, age_band, driving_style
  evidence: {field: "verbatim words"}           # FR-017
asked: + KM_PER_YEAR, FAMILY_SIZE, PRIORITY, GEARBOX          # profile_gaps questions
compare_level: BASE|MID|TOP, compare_level_source: DEFAULT|USER_TRIM        # FR-029
pending.items[].attempts: int, pending.items[].not_understood: str       # FR-031 re-ask loop
last_report: {fingerprint, blocks_hash, insights_hash}        # to prove a critique changed the report
```

## Computed structures (not stored; persisted in the turn's computations for audit)

- **Insight**: `{id, attribute, label, cars: [{car_id, value, unit, source_ids}], diff, rel_diff, unit,
  meaningful, better_car, relevance, confidence}`.
- **TradeOff**: `{gain_insight, cost_insight, break_even: {years|km}, text_numbers}`.
- **Verdict**: `{pick_car_id | null, tie, reasons: [insight ids], trade_off, confidence: HIGH|MEDIUM|LOW,
  confidence_reason, would_change: {insight id, condition}}`.
- **DataPanelEntry**: `{car_id, area, status: COMPLETE|PARTIAL|MISSING|UNAVAILABLE, reason, last_attempt,
  findable}`.
- **Suggestion**: `{id, label (i18n key + args), request: {kind, text, focus_cars, areas}}`.

## Configuration

| File | Content |
|---|---|
| `insights.yaml` | per attribute: `threshold_abs`, `threshold_rel`, unit, money conversion (per year at the user's km) |
| `sense.yaml` | per attribute: magnitude ranges, unit hints, meaning rules (e.g. CVT ⇒ no gear count), result ranges (TCO per class) |
| `report_layouts.yaml` | per profile: sections in order, `open_by_default`, `depth` |
| `tech_explainers.yaml` | technology → short explanation, consequences (consumption, reliability, feel), source |
| `generations.yaml` | optional `transmissions`, `drives` per generation |
