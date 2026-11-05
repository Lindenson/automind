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

## GET /series?metric=capability_score&labels=domain:km77.com,area:specs&days=90
`{"metric": "...", "series": [{"labels": {...}, "points": [{"day": "2026-11-05", "value": 0.71, "samples": 14}]}]}` — from `metric_daily`; used by every chart.

## GET /inaccuracies?area=&domain=&blame=&days=30
`[{signal_id, created_at, variant, car_name, attribute, shown_value, corrected_value, domain, url, quote, blame, kind, chat_id, turn_id}]` + `trend` (daily wrong values).

## GET /complaints?kind=&lang=&days=30
`[{feedback_id, created_at, kind, rating, text, request_kind, language, chat_id, turn_id, attribute, domain}]` + `trend` per kind.

## GET /diagnostics
```json
{"loops": [{"name":"insight","last_ok":"…","last_error":null,"fails_in_row":0,"next_due":"…","stale":false}],
 "models": [{"role":"interpreter","calls_24h":40,"fallback_share_1h":0.0,"errors_24h":{"quota":2}}],
 "search": {"calls_24h":30,"failures_24h":1}, "fetch": {"ok":120,"robots":8,"error":3},
 "readers": [{"reader":"km77","ok_share_7d":0.9,"ok_share_30d":0.92,"zero_streak":0}],
 "jobs": {"failed_24h":1}, "spend": {...}}
```

## GET /alerts?state=firing|all&days=30
`[{id, rule_id, subject, severity, title, value, threshold, started_at, last_seen_at, resolved_at, acknowledged_at, muted: bool, link}]`. `GET /alerts/summary` → `{"firing": {"critical":1,"warning":2}}` for the badge.

## POST /alerts/{id}/ack · POST /alerts/mutes `{rule_id, subject?, hours, note?}` · DELETE /alerts/mutes/{id}

## POST /changes/{id}/revert
Restores `before`; journals a new change `author=owner` with `reverted_by` set on the original. 409 if a later change on the same capability exists (revert the latest first).
