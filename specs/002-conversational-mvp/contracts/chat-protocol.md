# Contract: Chat Protocol v2 (WebSocket) and UI Blocks

Extends the demo protocol (`docs/demo-protocol.md`, v1) and stays backward-compatible. Clients
ignore unknown message and block types.

**Endpoint**: `ws://127.0.0.1:8000/ws/chat/{chat_id}`. `chat_id` is a client-generated UUID.

## Client → server

```jsonc
{ "type": "hello", "last_seq": 42 }                     // on (re)connect: replay events with seq > last_seq
{ "type": "user_message", "message_id": "uuid", "text": "..." }
{ "type": "confirm", "request_id": "uuid", "choice": "run" | "skip" | "option:<id>" | "edit", "text": "optional free text" }
{ "type": "cancel", "turn_id": "uuid" }
```

A `user_message` sent while a confirmation is pending resumes the turn with that text. The hub
interprets it: it may be a correction instead of a yes (research R2).

## Server → client

Every server message carries `seq` (monotonic per chat) and `turn_id`.

```jsonc
{ "type": "user_message_ack", "message_id", "created_at" }
{ "type": "status", "stage": "understanding|asking|resolving|cache|estimating|researching|validating|followup|computing|composing|done",
  "text": "...", "car": "optional label", "area": "optional area" }
{ "type": "case_file", "version": 7, "case": { /* CaseFile JSON, data-model §2 */ }, "changes": ["persona: UNKNOWN → BUYER", "car#2 replaced: Prado J250 → Prado 150 (used, ~2015)"] }
{ "type": "confirm_request", "request_id": "uuid", "kind": "variants" | "cost",
  "text": "markdown question in user's language",
  "options": [ { "id": "a1", "label": "Toyota Land Cruiser Prado 150 3.0 D-4D (2009–2017)", "detail": "used, ~2015" } ],
  "estimate": { "eur": 0.42, "cars": 2, "areas": ["specs","reliability","used_issues"], "depth": "STANDARD" } }
{ "type": "usage", "llm_calls": 23, "input_tokens": 51000, "output_tokens": 4800, "search_calls": 9, "cost_eur": 0.21 }
{ "type": "assistant_message", "message_id", "created_at", "text": "markdown", "blocks": [ /* Block[] */ ], "action": "REPORT" }
{ "type": "turn_cancelled" }
{ "type": "error", "text": "..." }
```

## Blocks

Unchanged from v1: `spec_table`, `metric_bars`, `race_chart`, `maintenance` (deprecated →
`tco`), `sources`, `notice`. `profile_scores` is accepted, but new backends send
`criteria_scores`. Block **order is significant**: the backend orders blocks per persona
(FR-030).

```ts
type Basis = "SOURCED" | "ASSUMPTION";
type Block =
 | /* v1 blocks … */
 | { type: "case_summary"; persona: "EXPERT"|"PERFORMANCE"|"BUYER"|"UNKNOWN"; facts: string[]; cars: { key: string; label: string; condition: "NEW"|"USED"|"UNKNOWN"; year: number|null }[] }
 | { type: "criteria_scores"; title: string; criteria_version: number;
     criteria: { key: string; label: string; weight: number; definition: string }[];
     cars: { car_id: string; label: string; ranked: boolean; total: number | null; coverage: number;
             parts: Record<string, { score: number | null; insufficient: boolean; inputs: string[] }> }[];
     winner_car_id: string | null; unmapped_wishes: string[] }
 | { type: "tco"; title: string; annual_km: number;
     cars: { car_id: string; label: string; condition: "NEW"|"USED"; age_years: number | null;
             annual_total: number; five_year_total: number;
             items: { kind: "MAINTENANCE"|"ENERGY"|"TYRES"|"ROAD_TAX"|"BIG_TICKET"|"BASE_RESERVE"; label: string;
                      annual_eur: number | null; five_year_eur: number | null; basis: Basis; inputs: string[]; sources: SourceRef[] }[] }[] }
 | { type: "reliability"; title: string;
     cars: { car_id: string; label: string; minimum_met: boolean;
             issues: { component: string; description: string; recurrence: "RECURRING"|"ISOLATED"; severity: "LOW"|"MEDIUM"|"HIGH";
                       age_window: string | null; sources: SourceRef[] }[];
             stats: { source: string; metric: string; value: string; year: number | null; url: string }[];
             none_found: boolean }[] }
 | { type: "reviews"; title: string;
     cars: { car_id: string; label: string; minimum_met: boolean; review_count: number; source_count: number;
             pros: { tag: string; text: string; recurring: boolean; sources: SourceRef[] }[];
             cons: { tag: string; text: string; recurring: boolean; sources: SourceRef[] }[] }[] }
 | { type: "engineering"; title: string;
     cars: { car_id: string; label: string; items: { key: string; label: string; display: string; confidence: Confidence; sources: SourceRef[] }[] }[] }
 | { type: "manufacturer"; title: string; makes: { make: string; facts: { kind: "HISTORY"|"KEY_MODEL"|"MARKET_POSITION"; text: string; sources: SourceRef[] }[] }[] };
```

## Persona block order (backend rule, FR-030)

| Persona | Order |
|---|---|
| BUYER | case_summary, criteria_scores, tco, reliability, reviews, spec_table (practicality rows first), sources |
| PERFORMANCE | case_summary, race_chart, metric_bars, criteria_scores, spec_table, reliability, tco, sources |
| EXPERT | case_summary, engineering, spec_table (all tiers), metric_bars, criteria_scores, reliability, manufacturer, tco, race_chart, sources |
| UNKNOWN | case_summary, criteria_scores, spec_table, tco, reliability, race_chart, sources |

Notices come first when they carry warnings (ambiguity, insufficient data, limits).
