# Contract: REST API and MCP Tools

## REST (`/api/v1`, JSON; localhost-bound; single local user)

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/api/v1/health` | Status, models per role, search provider, key presence (booleans only), MCP tool names | `{status, models, search, keys, mcp_tools}` |
| GET | `/api/v1/chats` | Chat list (FR-045), newest first | `{chats: [{id, title, updated_at, cars: [label], persona}]}` |
| GET | `/api/v1/chats/{id}/messages` | History | `{messages: ChatMessage[]}` |
| GET | `/api/v1/chats/{id}/case` | Current case file | `{version, case, changed_by}` |
| PATCH | `/api/v1/chats/{id}/case` | User edit (FR-009): persona, usage, budget, annual_km, rates_override, depth, weights (sets `weights_overridden`), remove priority | `{version, case}`; 409 if a turn is RUNNING; 422 on validation error |
| GET | `/api/v1/criteria` | Criteria dictionary (current version) | `{version, criteria: [...]}` |
| GET | `/api/v1/config/rates` | TCO rates and the reserve table (read-only in the MVP UI) | `{...}` |

The demo paths `/api/health` and `/api/chats/{id}/messages` stay as aliases until the frontend uses v2. Errors use `{code, message, details?}`. Secrets are never returned.

## MCP server `automind` (stdio; deterministic; no web access)

Analyst roles get the subsets below (least privilege, constitution VIII). Every tool returns JSON
with explicit units, `provenance`/`basis` labels and `version` fields.

| Tool | Args | Returns | Roles |
|---|---|---|---|
| `get_case` | chat_id | Case file (read-only) | all analysts |
| `get_vehicle_specs` | car_id, tier? | Specs with provenance, confidence, source count, unavailable list | reporters, answerer |
| `compute_metrics` | car_ids | Raw metrics with units (power_to_weight kW/t …), **labelled as metrics, not scores** | reporters, answerer |
| `score_criteria` | chat_id, car_ids, weights? | criteria_scores payload (scores 0–100 **labelled as scores**), with coverage and insufficient flags | reporters, answerer |
| `simulate_drag_race` | car_ids, settings | Race results (SIMULATED_ESTIMATE, model version, assumptions) | performance and expert reporters, answerer |
| `compute_tco` | chat_id, car_ids, annual_km? | TCO items (SOURCED/ASSUMPTION), annual and 5-year totals | buyer and balanced reporters, answerer |
| `get_reliability` | car_id | Issues and stats with recurrence and minimum_met | all reporters, answerer |
| `get_reviews` | car_id | Pros and cons with recurrence and minimum_met | buyer and balanced reporters, answerer |
| `get_engineering` | car_id | Tier 2 engineering items | expert reporter, answerer |
| `get_manufacturer` | make | Manufacturer facts | expert reporter |
| `list_catalog` | query | Catalog variants (id, label, generation years) | answerer |

Tools never start research and never fetch the web. Research is a graph action decided by the
policy (research R5).
