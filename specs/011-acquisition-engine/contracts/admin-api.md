# Contract: Admin API additions (`/api/v1/admin`, spec 011 US6)

Same guard as spec 010 (`admin_ok`: bearer `ADMIN_TOKEN` or loopback when none is set). All lists newest first,
`limit` default 50, max 500. Times ISO 8601 UTC.

## Parsers

`GET /parsers` →
```json
[{"reader": "km77", "domains": ["km77.com"], "frozen": false, "active": "km77@v5",
  "versions": [{"key": "km77@v5", "status": "active", "author": "agent:parser_doctor", "activated_at": "…"},
               {"key": "km77@v4", "status": "superseded"}],
  "last_7d": {"pages": 63, "fields_per_page": 11.0, "pass_rate": 0.95},
  "baseline_30d": {"fields_per_page": 11.3, "pass_rate": 0.96},
  "drift": null,
  "canary": {"change_id": "…", "phase": "watch", "ends_at": "…"}}]
```

`GET /parsers/{reader}` → the above for one reader plus `daily: [{version_key, day, pages, fields_per_page,
pass_rate, zero_pages, structure_hash, structure_sim}]` (60 days), `drift_signals: [{day, kind (yield_drop |
pass_drop | structure | zero_streak), detail}]`, `spec` of each version.

`POST /parsers/{reader}/rollback` body `{"to": "km77@v4"}` → re-activates that version (owner change journalled in
`acq_changes`, `author=owner`, status `reverted` on the change that installed the current one). 409 when `to` is not a
previous version of this reader.

`POST /parsers/{reader}/freeze` / `…/unfreeze` → no agent proposal targets a frozen reader (journalled).

## Changes

`GET /changes?origin=engine|registry&agent=&object_kind=&status=&days=30` → unified list:
```json
[{"id": "…", "origin": "engine", "created_at": "…", "author": "agent:parser_doctor",
  "object_kind": "parser", "object_key": "km77", "from_version": "km77@v4", "to_version": "km77@v5",
  "status": "watch", "explanation": "km77 parser v4→v5: table labels changed on 03.11; v5 reproduces 48/50 gold values; shadow yield 0.91 vs 0.42",
  "gates": {"replay": {"verdict": "pass"}, "shadow": {"verdict": "pass"}, "watch": {"day": 2, "of": 7}},
  "revertible": true}]
```
Registry rows map to `origin: "registry"`, `object_kind: "source"`, `explanation = reason`, `gates: null`.

`GET /changes/{id}` → full row: `diff`, `reason`, `evidence` (snapshot ids with URLs, gold ids, signals),
`gates` with `metrics_old/new`, `metrics_before/after`, `cost_eur`, experiment daily metrics.

`POST /changes/{id}/revert` → engine changes: re-activate `from_version` (or remove the override), status `reverted`,
journal an owner row; registry changes: delegate to 010's `POST /sources/changes/{id}/revert`. 409 when a later
change on the same object exists or the change is not accepted yet (then use `…/reject`).

`POST /changes/{id}/reject` → stop a change in `proposed|replay|shadow` (status `rejected`, reason "owner").

`POST /changes/{id}/forbid-similar` body `{"days": 30 | null}` → `change_blocks` row for (object_kind, object_key,
lever).

## Accuracy drill-down (FR-021, SC-010: ≤ 3 clicks from the KPI to the quote)

1. `GET /accuracy?days=30` → `{kpi: {wrong_share, baseline}, by_component: [{component: "parser:km77@v4", wrong: 7,
   right: 120, acc_lb: 0.9}, {component: "source:motor.es", …}], by_area: [...]}` (click 1: a component)
2. `GET /accuracy/{component}/values?days=30` → wrong values: `[{signal_id, variant, attribute, ours, truth,
   truth_origin, blame_vector, claim_id, created_at}]` (click 2: a value)
3. `GET /values/{claim_id}` → `{claim, evidence: {url, domain, source_type}, quote, snapshot: {id, fetched_at,
   url}, producer, producer_version, model, signals: [...]}` and `GET /snapshots/{id}/text?around=<quote>` → the
   page text window (≤ 4,000 chars) around the quote, as plain text (click 3: the page and quote).

## Engine status

`GET /engine` → `{worker: {beat_at, version, tasks_running}, tasks: {kind: {queued, running, failed_24h, dead}},
budgets_today: {agent: {spent, limit}}, baseline: {name, started_at, ended_at, values} | null, autonomy: bool}`.
