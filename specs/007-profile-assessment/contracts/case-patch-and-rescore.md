# Contract: case PATCH v2 and the rescore turn

## `PATCH /api/v1/chats/{chat_id}/case`

Body (all optional, `extra=forbid`). The existing fields are kept:
- persona;
- usage;
- budget;
- running_cost_limit, clear_running_cost_limit;
- needs;
- annual_km;
- rates_override;
- depth;
- weights;
- remove_priority.

New fields:

```json
{
  "profile": {"family": "FAMILY", "driving_style": "SPORTY", "region": "Sevilla", "age_band": "40_60"},
  "ownership_years": 8,
  "condition": "NEW",
  "weight_adjustments": {"safety": 10},
  "reset_weights": true
}
```

Field rules:
- `weights` (absolute, existing) is converted to `weight_adjustments` against the automatic weights.
- `reset_weights: true` clears every adjustment.
- Every patched field gets basis STATED.

Responses:
- `200` `{case_file, version, rescore: "started" | "queued" | "not_needed" | "research_needed", missing?: [...]}`:
  - `started`: a rescore turn began; events follow on the chat WebSocket;
  - `research_needed`: the change needs new data (for example `condition: USED`). Nothing starts; the UI shows an offer with the `missing` list.
- `409` if a turn is RUNNING (unchanged). The frontend keeps the patch and resends it after `turn_done`.

## Rescore turn (WebSocket events, existing envelope)

The turn uses the existing envelope and existing events. Order:
1. `turn_started{kind:"rescore"}`.
2. `case_file`.
3. `blocks` (criteria, tco, verdict, insights; each criterion row carries `delta` vs the previous report).
4. `message` (short "what changed" text).
5. `turn_done`.

Constraints:
- No `research_progress` events.
- 0 search calls; interpreter calls = 0; reporter calls ≤ 1.

## Weight breakdown in blocks

The `criteria_scores` block gains:

```json
{"weights": {"safety": {"final": 22.0, "base": 0, "manual": 10,
             "reasons": [{"code": "family.FAMILY", "points": 8}, {"code": "manual", "points": 10}]}},
 "capped": [], "manual": true}
```

The frontend localizes the reason codes.

## Profile on the case file (read)

The case file exposes:
- `basis: {field: "STATED"|"INFERRED"|"ASSUMED"}`;
- `profile.evidence: {field: "user words"}`;
- `ownership_years`.
