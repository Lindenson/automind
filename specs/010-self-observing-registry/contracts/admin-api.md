# Contract: Admin REST API

Two screens only (FR-029: detailed metrics and alerts are in Prometheus). All endpoints under `/api/v1/admin/`. Auth: `admin_ok()` (`api/access.py`) — `Authorization: Bearer <ADMIN_TOKEN>`, or loopback when no token is set. Failure → `403 {"detail":"forbidden"}`.

## Top problems

### GET /problems
The 10 open or regression issues with the highest impact (7 days).
```json
[{"id": "…", "rank": 1, "title": "Rephrased comparison requests in Russian", "component": "dialogue",
  "status": "open", "impact": 23.0, "failing_turns_7d": 9, "chats_7d": 4,
  "example_chat": "20b5b7f9…",
  "fix": {"kind": "config", "config_file": "questions.yaml", "config_key": "ASK_BUDGET.ru",
          "suggested_value": "…", "direction": null, "files": []}}]
```
`fix.kind` is `code` (with `files`, `direction`) or `config` (with `config_file`, `config_key`, `suggested_value`); `null` until diagnosed.

### GET /problems/{id}
Full issue: `examples` (chat, turn, quote, url, claim), `diagnosis` (`summary, likely_cause, fix, verify`), counts, first/last seen, status history, `copy_text` (markdown task for Claude Code).

### PATCH /problems/{id}
`{"status": "acknowledged"|"fixed"|"wontfix"|"open", "fixed_ref": "abc123"?}`.

## Sources

### GET /sources?area=specs
Per kind of data:
```json
{"area": "specs",
 "sources": [{"domain": "km77.com", "market": "ES", "status": "active", "rank": 1,
              "score": 0.71, "acc_mean": 0.93, "acc_lb": 0.84, "yield": 0.62, "attempts": 48,
              "frozen": false, "access": "ok"}],
 "counts": {"active": 7, "candidate": 3, "degraded": 1, "retired": 2, "blocked": 41}}
```

### GET /sources/changes?days=30&area=
Recent registry changes, newest first:
```json
[{"id": "…", "at": "…", "author": "system", "domain": "motor.es", "area": "used_price", "market": "ES",
  "change": "promoted|demoted|retired|reordered|added|blocked|unblocked|frozen|reverted",
  "before": {"status": "candidate", "rank": 5}, "after": {"status": "active", "rank": 2},
  "reason": "acc_lb 0.68 over 11 attempts; 3 values confirmed by independent families",
  "revertible": true}]
```

### GET /sources/{domain}
Source row, its capabilities, last 50 changes and signals (for the source card; access evidence with quotes).

### POST /sources/{domain}/freeze · /unfreeze · /block
Journalled with author `owner`. Lifting a deny-list, classifieds or terms block → 409 `{"detail":"hard limit: change config"}`.

### POST /sources/changes/{id}/revert
Restores `before`; journals a new change `author=owner, change=reverted`. 409 if a later change on the same capability exists.
