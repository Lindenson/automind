# Contract: Report Blocks and Protocol Additions (004)

Additive to protocol v2 (002/003). Unknown blocks are ignored by older clients.

## New blocks

```ts
type Confidence3 = "HIGH" | "MEDIUM" | "LOW";
type Block =
 | { type: "verdict"; headline: string;                 // one line, from the model, checked
     pick_car_id: string | null; tie: boolean;
     reasons: { text: string; insight_id: string }[];  // 2–3
     trade_off: { text: string; numbers: { label: string; value: number; unit: string }[] } | null;
     confidence: Confidence3; confidence_reason: string;
     would_change: string | null }
 | { type: "comparison"; rows: { key: string; label: string; unit: string | null;
       values: { car_id: string; display: string | null; missing: boolean; better: boolean }[];
       meaningful: boolean }[] }                      // rows without data for every car are omitted
 | { type: "data_panel"; cars: { car_id: string; label: string;
       areas: { area: string; status: "COMPLETE"|"PARTIAL"|"MISSING"|"UNAVAILABLE"; reason: string | null;
                findable: boolean }[] }[];
     changed: string | null }                         // after "find it": "+12 values: specs now complete"
 | { type: "value_retention"; cars: { car_id: string; label: string;
       points: { years: number; share: number | null; eur: number | null; basis: "SOURCED"|"ASSUMPTION";
                 market: string; sources: SourceRef[] }[] }[] }
 | { type: "suggestions"; items: { id: string; label: string; request: { kind: string; text: string;
       focus_cars?: string[]; areas?: string[] } }[] }
 | { type: "section"; key: string; title: string; open: boolean; depth: "summary"|"full";
     blocks: Block[] };                               // collapsible container for the layout
```

`criteria_scores` gains `relative: {car_id: number}` (best = 100) next to the absolute parts.
`manufacturer` facts gain kinds `MARKET_SHARE`, `FINANCIAL`, `RELIABILITY_REPUTATION`, `NETWORK_ES`.

## Client → server

```jsonc
{ "type": "find", "focus_cars": ["car#2"], "areas": ["specs", "reliability"] }      // "find it"
{ "type": "challenge", "car_id": "car#1", "attribute": "transmission", "text": "this is wrong" }
{ "type": "rating", "message_id": "…", "rating": 4, "note": "missing resale value" }
{ "type": "suggestion", "id": "s-why-1" }                                           // sends its request
```

## Server → client

```jsonc
{ "type": "progress", "car": "car#2", "area": "specs", "state": "searching", "accepted": 0 }
{ "type": "challenge_result", "car_id": "car#1", "attribute": "transmission",
  "outcome": "CORRECTED", "text": "automatic 6-speed (2 sources); 'manual' was another version" }
```

`assistant_message.language` (ru/es/en) drives the interface language unless the user chose one.
