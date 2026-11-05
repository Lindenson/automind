# Contract: Admin REST API

All endpoints under `/api/v1/admin/`. Auth: `admin_ok()` (`api/access.py`) — `Authorization: Bearer <ADMIN_TOKEN>`, or loopback when no token is set. Failure → `403 {"detail":"forbidden"}`. JSON only.

## GET /overview?days=7|30
```json
{
  "period": {"days": 7, "from": "...", "to": "..."},
  "satisfaction": {
    "overall": {"index": 0.62, "turns": 41, "prev": 0.58},
    "by_kind": [{"kind": "compare", "index": 0.55, "turns": 12, "prev": 0.61, "trend": [{"day": "2026-11-05", "index": 0.5}]}],
    "by_language": [{"key": "ru", "index": 0.6, "turns": 30}],
    "by_persona": [{"key": "BUYER", "index": 0.7, "turns": 9}]
  },
  "failure_classes": [{"class": "not_understood", "turns": 5, "share": 0.12}],
  "nodata_share": 0.18,
  "accuracy": {"right_w": 12.0, "wrong_w": 2.7, "share": 0.82},
  "fallback_share": [{"role": "interpreter", "share": 0.31, "calls": 40}],
  "spend": {"today_eur": 0.42, "month_eur": 6.1, "cap_eur": 5.0, "insight_eur": 0.05, "discovery_eur": 0.08},
  "top_declines": [{"kind": "compare", "delta": -0.12, "issue_ids": ["..."]}]
}
```

## GET /issues?status=open|all
`[{id, title, component, klass, key, status, count_total, count_7d, first_seen, last_seen, diagnosed: bool}]`, ordered by `count_7d` desc.

## GET /issues/{id}
Full issue incl. `examples`, `diagnosis`, and `copy_text` (markdown built by `insight/domain/issue_text.py`).

## PATCH /issues/{id}
Body `{"status": "acknowledged"|"fixed"|"wontfix"|"open", "fixed_ref": "abc123"?}` → updated issue. `fixed` sets `fixed_at=now`.

## GET /sources?area=specs&status=active
`[{capability_id, domain, area, market, status, score, acc_mean, acc_lb, yield, attempts, cost_per_value, last_change: {at, reason}, frozen, access}]`.

## GET /sources/{domain}
`{source: {...sources row}, capabilities: [...], changes: [... last 50], signals: [... last 50], attempts_summary: {...}}`.

## POST /sources/{domain}/block · /unblock-not-allowed
`block` → all capabilities `blocked`, journal author `owner`. There is no unblock for deny-list/classifieds/terms (409 `{"detail":"hard limit: change config"}`); a manual block can be lifted by `POST /changes/{id}/revert`.

## POST /sources/{domain}/freeze · /unfreeze
Sets `sources.frozen`; journalled.

## GET /changes?limit=100&author=system
`[{id, created_at, author, domain, area, market, field, before, after, reason, evidence, reverted: bool, held: bool}]` newest first.

## POST /changes/{id}/revert
Restores `before`; journals a new change `author=owner` with `reverted_by` set on the original. 409 if a later change on the same capability exists (revert the latest first).
