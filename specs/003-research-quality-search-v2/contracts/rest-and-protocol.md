# Contract: REST and Chat Protocol Changes (003)

Extends `specs/002-conversational-mvp/contracts/` (REST `/api/v1`, chat protocol v2). Everything not
listed here is unchanged. Protocol version stays `2` (additive changes only; unknown block types are
ignored by older clients).

## REST

| Method | Path | Purpose | Response |
|---|---|---|---|
| DELETE | `/api/v1/chats/{id}` | Delete one chat (FR-027–FR-030). Cancels a running/waiting turn first. Idempotent. | `200 {deleted: [id], counts: {table: n}}`; `200 {deleted: []}` if already deleted |
| POST | `/api/v1/chats/delete` | Delete several chats: body `{ids: string[]}` (1–100) | `200 {deleted: [id], counts: {table: n}}`; `422` on empty/oversized list |
| GET | `/api/v1/chats/{id}/messages`, `/case` | as 002 | **`410 {code: "chat_deleted"}`** for a deleted chat |
| PATCH | `/api/v1/chats/{id}/case` | as 002, plus `constraints` (partial: budget, running_cost_limit, usage) | `{version, case}`; `422` on invalid amounts/enums |
| GET | `/api/v1/health` | as 002; `search` becomes `{provider, fallback, keys: {serper: bool, tavily: bool, …}}` | booleans only, never key values |
| GET | `/api/v1/research/metrics?days=7` | Operator metrics (FR-017, FR-031): per area minimum-met share, pages rejected by reason, values rejected by reason, reader success per site, search cost, cache hits | `{areas: {...}, sites: [...], search: {...}}` |

Errors keep the 002 shape `{code, message, details?}`.

## WebSocket (chat protocol v2, additive)

Client → server: unchanged.

Server → client:

```jsonc
// hello for a deleted chat
{ "type": "error", "code": "chat_deleted", "text": "This chat was deleted." }   // then the server closes

// status stages gain: "searching" (provider call or cache), "reading" (fetch + reader),
// "relevance" (variant check), "feasibility"
{ "type": "status", "stage": "relevance", "text": "specs: 3 of 9 pages rejected (other generation)", "car": "BMW 5 Series G30 520d" }

// assistant_message.action gains "FEASIBILITY"
{ "type": "assistant_message", "action": "FEASIBILITY", "text": "…", "blocks": [ { "type": "feasibility", … } ] }

// confirm_request.kind gains "feasibility" (buttons for the verdict)
{ "type": "confirm_request", "request_id": "uuid", "kind": "feasibility",
  "text": "A new Land Cruiser does not fit €25,000. How do you want to continue?",
  "options": [ { "id": "report", "label": "Show the report anyway" },
               { "id": "used", "label": "Look at used ones (≈ 9–12 years)" },
               { "id": "alternatives", "label": "Suggest cars that fit" } ] }
```

The client answers with the existing `confirm` message (`choice: "report" | "used" | "alternatives"
| "edit"`, optional `text`). A typed reply is interpreted like any message.

## Blocks (additive)

```ts
type Verdict = "FITS" | "DOES_NOT_FIT" | "USED_ONLY" | "OTHER_CLASS" | "UNKNOWN";
type Num = { label: string; value: number | null; unit: string; basis: "SOURCED" | "ASSUMPTION"; sources: SourceRef[]; inputs: string[] };

type Block =
 | /* 002 blocks … */
 | { type: "feasibility"; title: string;
     constraints: string[];                       // human-readable, e.g. "Budget €25,000 (new or used)"
     cars: { car_id: string; label: string;
             checks: { check: "BUDGET"|"RUNNING_COST"|"USAGE_SPACE"|"USAGE_POWER"|"USAGE_RANGE";
                       verdict: Verdict;
                       summary: string;           // one sentence, numbers from code
                       compared: Num[];           // what was compared with what
                       used_age?: { from_years: number; to_years: number; basis: "EDITORIAL"|"ASSUMPTION" };
                       missing?: string[] }[] }[] };

// SourceRef gains optional fields (sources block and every block that lists sources):
type SourceRef = { name: string; url: string; type: SourceType; retrieved_at: string; excerpt?: string | null;
                   favourite?: boolean;                       // FR-012
                   extracted_by?: "READER" | "LLM";
                   rejected?: { reason: string; other?: string | null } | null };  // shown in the sources block only
```

The `sources` block lists accepted sources first, then (collapsed by default in the UI) rejected
pages with their reasons.

## Case file (protocol `case_file` event)

`case.constraints` and `case.feasibility_ack` as in [data-model.md](../data-model.md). The case panel
shows budget, running-cost limit and usage, editable through `PATCH …/case`.
