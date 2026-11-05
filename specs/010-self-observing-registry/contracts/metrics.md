# Contract: Prometheus metrics and alert rules

## Endpoint

`GET /metrics` — Prometheus text format 0.0.4. Auth: `Authorization: Bearer <METRICS_TOKEN>`; without `METRICS_TOKEN` only loopback and the Docker network (`AUTOMIND_METRICS_NETS`, default `127.0.0.0/8,172.16.0.0/12`). No DB query on scrape: gauges are served from an in-memory snapshot refreshed every 60 s by the metrics loop.

## Live counters and histograms (incremented at write points)

| Metric | Type | Labels |
|---|---|---|
| `automind_turns_total` | counter | `kind`, `status`, `action` |
| `automind_turn_duration_seconds` | histogram | `kind` |
| `automind_turn_failures_total` | counter | `class` |
| `automind_feedback_total` | counter | `kind` (rating, wrong_value, bad_source, complaint, rephrase, correction) |
| `automind_wrong_values_total` | counter | `area`, `blame` |
| `automind_llm_calls_total` | counter | `role`, `model`, `fallback` |
| `automind_llm_errors_total` | counter | `role`, `kind` (quota, overload, other) |
| `automind_llm_cost_eur_total` | counter | `role` |
| `automind_search_calls_total` | counter | `provider`, `cached`, `ok` |
| `automind_fetch_total` | counter | `outcome` (ok, robots, denied, error, timeout) |
| `automind_registry_attempts_total` | counter | `area`, `outcome` |
| `automind_registry_changes_total` | counter | `field`, `author` |
| `automind_alert_notifications_total` | counter | `rule`, `state` |

## Snapshot gauges (refreshed every 60 s)

| Metric | Labels |
|---|---|
| `automind_satisfaction_index` | `kind`, `window` (7d, 30d) |
| `automind_satisfaction_turns` | `kind`, `window` |
| `automind_accuracy_share` | `area`, `window` |
| `automind_nodata_share` | `area`, `window` |
| `automind_complaints_24h` / `automind_complaints_daily_avg_30d` | `kind` |
| `automind_capabilities` | `area`, `status` |
| `automind_active_sources` | `area`, `market` |
| `automind_source_score` / `automind_source_accuracy_lb` / `automind_source_yield` | `domain`, `area`, `market` (only candidate, active, degraded) |
| `automind_source_wrong_values_24h` | `domain` (only domains with ≥ 1) |
| `automind_reader_zero_streak` | `reader` |
| `automind_llm_fallback_share` | `role`, `window` (1h, 7d) |
| `automind_provider_unavailable_seconds` | `provider` |
| `automind_spend_today_eur` / `automind_daily_cap_eur` | — |
| `automind_background_spend_today_eur` / `automind_background_budget_eur` | `loop` |
| `automind_loop_last_success_timestamp_seconds` / `automind_loop_fails_in_row` / `automind_loop_interval_seconds` | `loop` |
| `automind_issues` | `component`, `status` |
| `automind_alerts_firing` | `rule`, `severity` |

Label cardinality: `kind` ≤ 15, `area` 12, `market` ≤ 10, `domain` ≤ ~300 (filtered by status).

## Alert rules (`config/alerts.yaml` → `deploy/prometheus/automind-rules.yml`)

| Rule id | Condition (in-app ≡ PromQL template) | Severity |
|---|---|---|
| `satisfaction_drop` | index 7d < index 30d − 0.15 and turns 7d ≥ 10, per kind | warning |
| `complaint_spike` | complaints 24h > 3 × daily avg 30d and ≥ 3, per kind | warning |
| `inaccuracy_high` | accuracy 7d < 0.85 with ≥ 10 signals, per area | critical |
| `source_wrong_burst` | wrong values 24h ≥ 3 for one domain | warning |
| `source_degraded` | an active capability became degraded/blocked (registry change event; Prom: `increase(automind_registry_changes_total{field="status"})` with snapshot `automind_capabilities{status="degraded"}` rising) | warning |
| `sources_below_min` | active sources < min per area × market | warning |
| `reader_zero` | reader zero streak ≥ 5 | critical |
| `nodata_rise` | nodata 7d > nodata 30d + 0.15, per area | warning |
| `fallback_high` | fallback share 1h > 0.2, per role | warning |
| `provider_down` | provider unavailable ≥ 5 min | critical |
| `budget_80` | spend today ≥ 0.8 × cap | warning |
| `background_budget_used` | background spend ≥ budget, per loop | warning |
| `loop_stale` | now − last success > 2 × interval, per loop | critical |
| `loop_failing` | fails in row ≥ 2, per loop | critical |
| `issue_regression` | an issue moved to regression | warning |

`scripts/alerts_to_prom.py` renders each rule's PromQL template with its thresholds; `tests/unit/test_alert_rules_sync.py` regenerates and diffs the committed file.

## Webhook (optional)

`ALERT_WEBHOOK_URL` — POST JSON:
```json
{"state":"firing|resolved","rule":"source_degraded","severity":"warning","title":"km77.com specs/ES degraded","value":0.41,"threshold":0.45,"started_at":"…","resolved_at":null,"link":"https://<host>/admin/sources/km77.com"}
```
Max `alerts.webhook_per_hour` (default 20) messages; 2 retries; failures counted, never block the loop.
