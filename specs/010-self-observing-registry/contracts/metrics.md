# Contract: Prometheus metrics and alert rules

All detailed metrics and all alerts live in Prometheus (US9). The admin page shows only top problems and source quality.

## Endpoint

`GET /metrics` — Prometheus text format. Auth: `Authorization: Bearer <METRICS_TOKEN>`; without `METRICS_TOKEN` only loopback and the Docker network (`AUTOMIND_METRICS_NETS`, default `127.0.0.0/8,172.16.0.0/12`). No DB query on scrape (FR-031): gauges come from an in-memory snapshot refreshed every 60 s.

## Counters and histograms (live, at write points)

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
| `automind_research_jobs_total` | counter | `area`, `status` |
| `automind_registry_attempts_total` | counter | `area`, `outcome` |
| `automind_registry_changes_total` | counter | `change`, `author` |

## Snapshot gauges (every 60 s)

| Metric | Labels |
|---|---|
| `automind_satisfaction_index`, `automind_satisfaction_turns` | `kind`, `window` (7d, 30d) |
| `automind_satisfaction_index_by` | `dim` (language, persona), `key`, `window` |
| `automind_accuracy_share`, `automind_accuracy_signals` | `area`, `window` |
| `automind_nodata_share` | `area`, `window` |
| `automind_complaints_24h`, `automind_complaints_daily_avg_30d` | `kind` |
| `automind_capabilities` | `area`, `status` |
| `automind_active_sources` | `area`, `market` |
| `automind_source_score`, `automind_source_accuracy_lb`, `automind_source_yield` | `domain`, `area`, `market` (candidate, active, degraded only) |
| `automind_source_wrong_values_24h` | `domain` (≥ 1 only) |
| `automind_reader_zero_streak` | `reader` |
| `automind_llm_fallback_share` | `role`, `window` (1h, 7d) |
| `automind_provider_unavailable_seconds` | `provider` |
| `automind_spend_today_eur`, `automind_daily_cap_eur` | — |
| `automind_background_spend_today_eur`, `automind_background_budget_eur` | `loop` |
| `automind_loop_last_success_timestamp_seconds`, `automind_loop_fails_in_row`, `automind_loop_interval_seconds` | `loop` (insight, registry, metrics, retention) |
| `automind_issues` | `component`, `status` |

Cardinality: `kind` ≤ 15, `area` 12, `market` ≤ 10, `domain` ≤ ~300 (status-filtered).

## Shipped rules (`deploy/prometheus/automind-rules.yml`)

| Alert | Expression (sketch) | for | Severity |
|---|---|---|---|
| `AutomindSatisfactionDrop` | `index{window="7d"} < index{window="30d"} - 0.15 and turns{window="7d"} >= 10` | 30m | warning |
| `AutomindComplaintSpike` | `complaints_24h > 3 * complaints_daily_avg_30d and complaints_24h >= 3` | 15m | warning |
| `AutomindInaccuracyHigh` | `accuracy_share{window="7d"} < 0.85 and accuracy_signals{window="7d"} >= 10` | 30m | critical |
| `AutomindSourceWrongBurst` | `source_wrong_values_24h >= 3` | 0m | warning |
| `AutomindSourceDegraded` | `increase(registry_changes_total{change=~"demoted|blocked"}[15m]) > 0` | 0m | warning |
| `AutomindSourcesBelowMin` | `active_sources < 2` | 1h | warning |
| `AutomindReaderZero` | `reader_zero_streak >= 5` | 0m | critical |
| `AutomindNoDataRise` | `nodata_share{window="7d"} > nodata_share{window="30d"} + 0.15` | 1h | warning |
| `AutomindFallbackHigh` | `llm_fallback_share{window="1h"} > 0.2` | 15m | warning |
| `AutomindProviderDown` | `provider_unavailable_seconds >= 300` | 0m | critical |
| `AutomindBudget80` | `spend_today_eur >= 0.8 * daily_cap_eur` | 0m | warning |
| `AutomindBackgroundBudgetUsed` | `background_spend_today_eur >= background_budget_eur` | 0m | warning |
| `AutomindLoopStale` | `time() - loop_last_success_timestamp_seconds > 2 * loop_interval_seconds` | 5m | critical |
| `AutomindLoopFailing` | `loop_fails_in_row >= 2` | 0m | critical |
| `AutomindIssueRegression` | `automind_issues{status="regression"} > 0` | 0m | warning |
| `AutomindDown` | `up{job="automind"} == 0` | 2m | critical |

Each rule carries `annotations.summary` and `annotations.admin` (link to `/admin` where useful). `tests/unit/test_prom_rules.py` parses the file and checks every `automind_*` name exists in the exporter registry (FR-032). Routing is configured by the owner in Alertmanager (`deploy/prometheus/alertmanager.yml` ships a placeholder receiver).
