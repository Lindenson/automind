# Implementation Plan: Self-Observing AutoMind and an Autonomous Source Registry

**Branch**: `010-self-observing-registry` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-self-observing-registry/spec.md`

## Summary

Three additions, each behind its own boundary, none slowing a turn:

1. **Observation** (US1, US2): every turn gets a `turn_outcomes` row (failure classes, signals, score 0–1) computed by a pure function `domain/outcome.py`; the interpreter returns a new `relation` field in the call it already makes; all user signals land in one `feedback` table (rating, "wrong?", new "bad source", complaint, rephrase, correction); `llm_calls` gains `primary_model`, `fallback`, `prompt_name`, `prompt_version`, `prompt_hash`.
2. **Insight** (US3–US5): a new package `automind.insight` with a pure clustering core (`insight/domain`) and an in-process daily loop (like `retention_loop`). Groups above a threshold become deduplicated `issues`; within a daily budget an `analyst` model call writes diagnosis, cause, direction, likely files and verification; the admin page copies it as a Claude Code task. The loop has **no write path** to code, config or prompts. Fixed issues that grow again reopen as `regression`.
3. **Acquisition registry** (US6–US8): a new package `automind.acquisition.registry` (pure `domain/`: score, lifecycle, limits, admission rules; `application/`: planner and review use cases behind ports; `infrastructure/`: repositories, admission fetcher). Research asks the registry for source order per (car, kind of data = research area, market) and records every attempt. A daily review moves capabilities through the lifecycle, runs bounded discovery and admission, journals every change in `registry_changes`, and honours hard limits checked in code. Seeded from `sources.yaml` favourites, the 009 survey and `learned_sources`; `learned.py` is retired. A flag `registry.autonomy` keeps the first release behaviour-identical.

4. **Metrics and alerts** (US9): daily rollups in `metric_daily` feed the admin charts (Sources, Inaccuracies, Complaints, Self-diagnostics); a `/metrics` endpoint (`prometheus_client`) exports live counters and snapshot gauges; alert rules in `config/alerts.yaml` are evaluated every 5 minutes by a pure evaluator, kept as firing/resolved `alerts` with ack and mutes, sent to an optional webhook, and rendered into Prometheus rules (`deploy/prometheus/automind-rules.yml`) with a drift test. Every background loop writes a heartbeat so a silent stop is itself an alert.

An admin SPA view at `/admin` (no router dependency: path switch in `main.tsx`) uses new REST endpoints under `/api/v1/admin/*` guarded by `admin_ok`.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript + React 18 (frontend)

**Primary Dependencies**: FastAPI, LangGraph, SQLAlchemy/asyncpg, Alembic, Pydantic, httpx (existing fetcher); zustand + zod + echarts (already used) on the frontend. One new backend dependency: `prometheus_client` (FR-035). Optional `monitoring` compose profile: Prometheus + Alertmanager (pinned images).

**Storage**: PostgreSQL. Migrations `0014_observation`, `0015_insight`, `0016_registry`, `0017_metrics_alerts`. Existing `report_ratings`, `value_challenges` stay (written as before, mirrored into `feedback`); `learned_sources` is read once by the seed and then left unused (dropped in a later spec).

**Testing**: pytest unit tests for the pure cores (`domain/outcome.py`, `insight/domain`, `acquisition/registry/domain`) including seeded property tests (no new dependency); integration tests on `automind_test`; graph tests with fake LLM for `relation` and outcomes; golden g1–g12 unchanged with autonomy off; a new fixture scenario `registry` under `tests/fixtures/scenarios/`; frontend `npm test` for the admin store and the bad-source button.

**Target Platform**: Linux server, Docker Compose (single `app` process, `--workers 1`).

**Project Type**: web service + SPA.

**Performance Goals**:
- outcome write ≤ 1 DB insert/update per turn; no extra LLM call per turn;
- the registry plan for a job is one indexed query (cached per job);
- daily insight run over 30 days of data < 30 s of DB time;
- `/metrics` scrape served from memory (< 50 ms); rollup run for today < 5 s; alert evaluation every 5 min.

**Constraints**:
- background work runs in the API process as asyncio tasks (ADR-026: one process); never holds the per-chat lock;
- insight analysis budget and discovery budget per day (config), both inside `DAILY_CAP_EUR`;
- hard limits (deny-list, classifieds, robots/terms, budgets, frozen) enforced in `acquisition/registry/domain/limits.py` on every change; config for limits is not writable by any code path of the system.

**Scale/Scope**: one owner, a handful of users; ≈ 200 sources × 12 areas × ≈ 6 markets ≈ a few thousand capabilities; tens of issues.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I Evidence first | Registry changes order and admission only; values still pass relevance, excerpt, sense, plausibility. Candidate values labelled "unverified source", half weight. | Pass |
| II Exact identity | Unchanged; "wrong car" becomes a measured class. | Pass |
| III Deterministic computation | Score, lifecycle, outcome score, clustering are pure code; the LLM only writes diagnosis prose and reads terms pages (quote required). | Pass |
| IV Provenance | `unverified source` label added for candidates. | Pass |
| V Layered monolith | New packages `insight`, `acquisition.registry` with import-linter contracts: chat cycle imports only `acquisition.registry.api`; `insight` imports neither cycle's internals; both `domain` parts pure. | Pass |
| VI Human-steered (v1.2.0) | Code, rules, prompts, parsers never changed by the system (no write path exists). Source order and status are XII territory. | Pass |
| VII Provider independence | `analyst` and `terms_reader` roles through the gateway; per-call tracking extended. | Pass |
| VIII Untrusted content | Terms reader is a web reader (no tools, structured output with quote checked to occur in the page); diagnosis reads examples as data, no tools. | Pass |
| IX Test-first, reproducibility | Pure cores tested first; `prompt_hash`/`prompt_version` recorded per call. | Pass |
| X YAGNI | No queue, worker container, canary or bandit; in-process loop; Wilson bound instead of Bayesian machinery. `prometheus_client` added for a stated requirement (FR-035); Prometheus/Alertmanager only in an optional profile. | Pass |
| XI Quality gates | "No data" only after active sources + bounded discovery; sources tried listed. | Pass |
| XII Self-observation & bounded autonomy | Outcomes, feedback, issues, journal, revert, limits, metrics, alerts, loop heartbeats — the feature itself. | Pass |

Post-design re-check: Pass (no Complexity Tracking entries).

## Project Structure

### Documentation (this feature)

```text
specs/010-self-observing-registry/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── admin-api.md     # REST /api/v1/admin/*
│   ├── ws-feedback.md   # WS bad_source + feedback acks
│   ├── metrics.md       # /metrics, alert rules, webhook
│   └── registry-port.md # the only interface research uses
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 0014_observation.py          # turn_outcomes, feedback, llm_calls columns
│   ├── 0015_insight.py              # issues, insight_runs
│   ├── 0016_registry.py             # sources, capabilities, truth_signals, registry_changes, registry_attempts
│   └── 0017_metrics_alerts.py       # metric_daily, loop_heartbeats, alerts, alert_mutes
├── config/
│   ├── outcome.yaml                 # signal weights, class rules thresholds
│   ├── insight.yaml                 # thresholds, budget, component → likely files map
│   ├── registry.yaml                # score weights, priors, half-life, lifecycle thresholds, budgets
│   └── alerts.yaml                  # alert rules: condition, threshold, window, severity, link
├── src/automind/
│   ├── domain/outcome.py            # pure: failure classes + score of a turn
│   ├── application/interpret.py     # + relation field
│   ├── orchestration/
│   │   ├── runner.py                # write/patch turn outcome in _done/_fail/cancel
│   │   └── prompts/interpreter.md   # relation rules; analyst_issue.md, terms_reader.md (new)
│   ├── infrastructure/
│   │   ├── llm_gateway.py           # prompt name/version/hash + primary/fallback via contextvar
│   │   ├── usage_callback.py        # writes new llm_calls columns
│   │   └── db/{models.py,repositories.py}  # OutcomeRepo, FeedbackRepo
│   ├── insight/
│   │   ├── domain/{clusters.py,issue_text.py}   # pure
│   │   ├── application/{analyse.py,ports.py}
│   │   ├── infrastructure/repo.py
│   │   ├── loop.py                  # insight_loop(), started in api/app.py lifespan
│   │   ├── metrics/{rollup.py,prom.py,heartbeat.py}   # daily rollups; Prometheus counters + snapshot collector
│   │   └── alerts/{evaluate.py,notify.py}            # pure evaluator in insight/domain/alerts.py; webhook
│   ├── acquisition/registry/
│   │   ├── api.py                   # RegistryPort: plan(), record(), signal()
│   │   ├── domain/{score.py,lifecycle.py,limits.py,admission.py,families.py}  # pure
│   │   ├── application/{review.py,discovery.py,seed.py,ports.py}
│   │   └── infrastructure/{repo.py,terms.py}
│   ├── application/
│   │   ├── research.py              # favourite_priority/_rank_hits/learned_sites/_record_learned → registry port
│   │   └── challenge.py             # writes feedback + truth signal; fills turn_id, claim_id
│   └── api/{ws.py,admin.py,metrics.py}  # bad_source message; /api/v1/admin/*; /metrics
└── tests/
    ├── unit/{test_alerts_eval.py,test_alert_rules_sync.py,test_rollup.py,test_outcome.py,test_insight_clusters.py,test_registry_score.py,test_registry_lifecycle.py,test_registry_limits.py}
    ├── integration/{test_feedback.py,test_registry_seed.py,test_insight_loop.py,test_admin_api.py}
    ├── graph/test_turn_outcomes.py
    └── fixtures/scenarios/registry/

deploy/prometheus/{prometheus.yml,automind-rules.yml,alertmanager.yml}   # rules generated by scripts/alerts_to_prom.py
docker-compose.yml                   # + optional profile "monitoring"

frontend/src/
├── main.tsx                         # "/admin" → <AdminApp/>
├── admin/{AdminApp.tsx,Overview.tsx,Issues.tsx,Sources.tsx,SourceCard.tsx,Changes.tsx,
│          Inaccuracies.tsx,Complaints.tsx,Diagnostics.tsx,Alerts.tsx,AlertBadge.tsx,Series.tsx,store.ts,api.ts}
├── components/badges.tsx            # SourceItem gets a "bad source" action
└── lib/protocol.ts                  # BadSourceOut, FeedbackAck
```

**Structure Decision**: web application (existing `backend/` + `frontend/`). New bounded contexts `insight` and `acquisition.registry` follow the layered pattern of the main package (pure `domain`, ports in `application`, adapters in `infrastructure`) and are guarded by new import-linter contracts. Research keeps living in `application/research.py`; only its four source-ordering/learning functions are rerouted through `acquisition.registry.api` (strangler step; the full pipeline extraction from the review backlog is not part of 010).

## Delivery order (each step releasable)

1. **Observation**: migration 0014, `relation`, `domain/outcome.py`, runner hooks, `feedback` (+ bad-source button), llm_calls columns; live Prometheus counters at the same write points; `/metrics`.
2. **Metrics and admin overview**: migration 0017, rollups, heartbeats, snapshot gauges; `/admin` shell + Overview, Complaints, Self-diagnostics tabs (baseline visible).
2b. **Alerts**: `config/alerts.yaml`, evaluator, alerts/mutes, badge + Alerts tab, webhook, generated Prometheus rules + drift test, optional monitoring profile.
3. **Insight**: migration 0015, clusters, issues, analyst diagnosis, copy text, regression reopen, Issues tab, seed of 009 issues.
4. **Registry, same behaviour**: migration 0016, seed, port, research rerouted, `registry.autonomy: false`; goldens unchanged.
5. **Registry autonomy**: score, lifecycle, review loop, discovery + admission, journal, revert/freeze/block, Sources (with series), Changes and Inaccuracies tabs, source alerts; flag on.

## Complexity Tracking

None.
