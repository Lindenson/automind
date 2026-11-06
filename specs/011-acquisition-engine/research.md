# Research: Spec 011 — Acquisition Engine

Decisions taken from the code as it is on 2026-11-05 (branch `011-acquisition-engine`, after spec 010), the external
review `docs/history/review-2026-11-05-acquisition.md` and constitution 1.3.0 (XII amended, XIII new). Each decision lists
what was rejected and why. Paths are relative to `backend/` unless they start with `frontend/`, `deploy/`,
`specs/`, `docs/` or `scripts/`.

## What exists and what it means for 011

- `application/research.py` (1,616 lines) is the whole pipeline: plan (`queries_for`, `registry_queries`,
  `learned_sites`, `_plan`), locate (`_rank_hits`, search part of `_collect`, `_search_pages`, `_ai_queries`), fetch
  (page part of `_collect` through `ports.page_store`), relevance (`_PageJudge`, `_store_relevance`), parse
  (`_read_tables` → `ports.readers`, `ex.extract`), validate (`_sense_before`, `_sense_ev_before`, `_check`,
  `_sense_after`, validator role inside `_spec_claims`), persist (`_evidence`, `_persist`, `_persist_reading`,
  `_items` and the per-area writers), merge (`reselect`, `fill_gearbox`, `_without_price_outliers`,
  `_interval_from_schedule`), bookkeeping (`_mark_run`, `_job_metrics`, `_record_registry`, `_record_learned`) and
  read-model queries used by the chat (`missing_critical`, `last_done`, `ev_counts`, `powertrains`, `registry_done`,
  `unmet_areas`, `accepted_gearboxes`, `mixed_families`).
- Chat-side callers: `orchestration/nodes/research.py` (`run_job`), `nodes/understand.py` (`powertrains`,
  `last_done`, `unmet_areas`, `registry_done`), `nodes/compute.py` (`ev_counts`, `unmet_areas`),
  `application/resolve.py` (`accepted_gearboxes`, `mixed_families`, and its own `ports.search`/`page_store` calls),
  `application/challenge.py` and `application/repair.py` (private `_check`, `_sense_before`, `_ReaderClaim`,
  `_plausibility_ctx`, `_known_values`, `reselect`), `application/lineup.py` and `application/versions.py` (their own
  search + fetch + web-reader LLM calls).
- `infrastructure/pages.py` keeps only the **main-content text** (trafilatura markdown, ≤ 60,000 chars) in
  `documents`, one row per normalised URL, **overwritten on re-fetch**. The raw HTML the site readers need exists
  only in memory (`Page.html`). Nothing can be replayed today.
- `claims.extracted_by` says READER or LLM, nothing about which reader version, prompt version or model.
  `llm_calls` (spec 010) has `prompt_name/version/hash` and the served model per call, but no link to claims.
- Site readers: `infrastructure/site_readers/__init__.py` (one generic label/value reader, layouts `table` and
  `divrow`), configured by `config/site_readers.yaml` (`version: 1` for the whole file; readers km77,
  ultimatespecs, auto_data — the last is deny-listed and never runs). Per-day counts in `site_reader_stats`
  (ok/failed/ambiguous per domain), a fail streak in memory.
- Registry (spec 010): `sources`, `capabilities` (decayed `attempts/accepted/right_w/wrong_w`, Wilson `acc_lb`,
  `yield`, `score = acc_lb × yield − λ·cost`), `truth_signals` (single `blame` string), `registry_changes`
  (journal + owner revert), `registry_runs`; daily `review()`; `autonomy: false`.
- Background loops run as asyncio tasks in the API lifespan (`api/app.py`): retention, metrics snapshot, registry
  review, insight.
- `eval/reference_vehicles.yaml` holds a small hand-made reference set with sourced specs: a first gold seed.

## R1. Snapshot storage, compression, retention

- **Decision**: store raw fetched bodies in PostgreSQL, content-addressed and compressed with zstd:
  - `snapshot_blobs(sha256 PK, body bytea zstd, raw_bytes, stored_bytes, codec)`: one row per distinct raw body
    (re-fetching an unchanged page costs no space). `ALTER TABLE … ALTER COLUMN body SET STORAGE EXTERNAL` so
    TOAST does not try to compress zstd output again.
  - `page_snapshots(id, url, url_hash, final_url, document_id, fetched_at, blob_sha256, content_type, http_status,
    status, retention_class, keep_until, accepted_values, variant_ids[], structure_hash, replayable)`: one row per
    fetch event; `documents` stays the page cache (text for extraction) and gains nothing but a pointer from the
    snapshot.
  - Compression: `zstandard` (Python package; the stdlib `compression.zstd` arrives only in 3.14 and the project
    requires ≥ 3.13), level 10, no dictionary in v1 (a trained dictionary per domain is a later optimisation,
    measured first). Expected ratio on spec pages 6–10× (a 200 KB km77 page → ~25 KB).
  - Retention classes: `accepted` (the page gave ≥ 1 accepted value or is referenced by a gold match) keep
    ≥ 180 days; `plain` keep ≥ 30 days; `pinned` (part of a running experiment's corpus) kept until the experiment
    ends. A size cap (`acquisition.yaml: snapshots.max_gb`, default 5) is enforced by the worker's retention task:
    over the cap, delete expired rows first, then the oldest `plain`, then the oldest `accepted` older than 180
    days; never `pinned`. Blobs without snapshots are deleted in the same pass.
  - Not replayable: PDFs are stored (the reader is `pdf`), but JS-only/empty pages (`NO_CONTENT`), refused and
    paywalled pages store metadata only (`replayable=false`, no blob): they are judged on live signals only and are
    never used to validate a parser (spec edge case).
  - Writer: `DbPageStore._from_raw` (US1) — every successful network fetch writes a snapshot; a page served from the
    cache does not create a new one (the snapshot of its last fetch is reused, linked by `document_id`).
- **Rationale**: one database keeps backup, `scripts/deploy.sh export/move` and the replay query simple (join
  snapshots → claims → gold in SQL). Volume: ≤ 8 pages per job, ~1,000 pages/day at the outside → ~25–30 MB/day
  compressed, ≈ 5 GB for 180 days in the worst case; well inside one Postgres.
- **Alternatives**: files on a volume (WARC or per-page `.html.zst`) — rejected: a second store to back up and move,
  orphan files, no transactional link to claims; object storage (MinIO) — new infrastructure (X); gzip — 20–30 %
  larger and slower to decompress; storing the main-content text only — readers need raw HTML.

## R2. Version identifiers for readers, prompts, models and stages

- **Decision**: plain text identifiers everywhere, no foreign keys between versioned objects and values, so US1 can
  record versions before the parser tables of US4 exist:
  - **Parser spec version**: `<reader_id>@v<N>` (e.g. `km77@v1`) plus `spec_hash` = sha256[:12] of the canonical
    JSON of the spec. US1 records `km77@v1` for all of today's readers (they become version 1 in US4 without any
    change in output, proven by T-test on stored pages).
  - **Extraction prompt version**: `<prompt_name>@v<N>` (e.g. `extract_specs@v3`) taken from the header comment
    `<!-- prompt: extract_specs v3 … -->` that the gateway already parses (spec 010 R1), plus the prompt hash. From
    US5 on, versions created by the extractor tuner live in `prompt_versions` and get N > the file's version.
  - **Model**: the model that actually answered (`provider:model`, as in `llm_calls.model`).
  - **Producer**: `claims.producer` = `reader` | `extractor` | `dataset` | `user`; `claims.producer_version` = the
    parser or prompt version; `claims.model` (null for readers); `claims.snapshot_id`.
  - **Stage versions**: each moved pipeline stage has a module constant `VERSION = "<stage>@<n>"`; a job records
    `stage_versions` (`{"plan": "plan@2", "locate": "locate@1", …}`) on its registry attempts and research run.
    A stage version is bumped by a person in code when behaviour changes.
  - **Relevance judge**: `page_relevance` gains `prompt_version` and `model` (method `LLM`), so relevance blame can
    name the version too.
- **Rationale**: SC-002 (100 % of values name their producer) with the cheapest change; text keys are stable across
  migrations, readable in the admin page and in journals ("km77 v4 → v5").
- **Alternatives**: FK to `parser_versions.id` from claims — forces US4 before US1; hashes only — not readable.

## R3. Open datasets for gold values

All four are datasets, not web pages: a `sources` row with `source_type = DATASET`, access `ok`, loaded by a worker
task with download + refresh, never through the fetch policy for web pages (they are official open-data APIs).
Exact column names are verified by the first loader task against a live sample and pinned in
`config/gold_datasets.yaml`; the loader fails loudly on a schema change.

| Dataset | What it gives | Format / access | Size | Licence | Refresh |
|---|---|---|---|---|---|
| **EEA CO2 monitoring, new passenger cars** (Reg. (EU) 2019/631) | per make / commercial name / type-variant-version / fuel: WLTP CO2 (g/km), fuel consumption (l/100 km, from 2021), electric energy consumption (Wh/km), electric range (km), engine power (kW), engine capacity (cm³), mass in running order and WLTP test mass (kg), registrations by country and year | EEA Discodata SQL API (JSON) or yearly CSV/ZIP from the EEA datahub | full year 1–3 GB CSV (row per registration group); **queried aggregated**: `GROUP BY` make, commercial name, fuel, power, capacity, mass → tens of MB per year | CC BY 4.0 (EEA standard re-use, attribution) | yearly final + provisional; monthly check |
| **EEA OBFCM real-world fuel/energy consumption** (Impl. Reg. (EU) 2021/392) | per make / model / fuel type: average real-world fuel consumption (l/100 km), electric energy (kWh/100 km), for PHEV the share of distance driven in charge-depleting mode | EEA datahub CSV per reporting year | small (aggregated per model, tens of MB) | CC BY 4.0 | yearly |
| **RDW Open Data** (Netherlands vehicle register) | per registered vehicle: make, commercial name, type/variant/version (type approval), empty mass, mass in running order, list price (`catalogusprijs`, NL), cylinders, displacement; fuel dataset: net max power (kW), combined consumption, CO2, WLTP electric consumption and electric range | Socrata SODA API (`opendata.rdw.nl`, JSON/CSV, SoQL with `$select/$group/$where`); datasets "Gekentekende voertuigen" (`m9d7-ebf2`) and "…brandstof" (`8ys7-d773`), joined by `kenteken` server-side through grouped queries per make/model | full ~16 M rows; **grouped queries per make + commercial name + type-approval variant/version** → a few MB per make | CC0 (public domain) | weekly for asked makes |
| **KBA** (Germany, Kraftfahrt-Bundesamt) | statistics of new registrations and stock per make/model (FZ series), emission classes | XLSX/CSV publications | small | free with attribution (Datenlizenz Deutschland – Namensnennung 2.0) | monthly |

- **Decision**:
  - EEA CO2 and RDW are the gold sources for **specifications** (power, displacement, mass, WLTP CO2 / consumption /
    Wh/km / electric range); EEA OBFCM is gold for **real-world consumption** (a separate attribute
    `consumption_real`, never mixed with WLTP); RDW `catalogusprijs` is not gold for Spanish prices (other market) —
    loaded as `list_price_nl` for plausibility only.
  - **KBA is not a gold source**: it publishes no per-variant specifications. It is used for popularity only (which
    models matter in DE for prefetch). FR-003's "at least one national register" is met by RDW.
  - Battery capacity (kWh) is **in none of these datasets**; it is checked by physics (R10: range × Wh/km) instead.
  - The reference set `eval/reference_vehicles.yaml` is loaded as gold with origin `reference_set`, confidence
    `HIGH` (hand-checked), and confirmed/corrected user challenges become gold with origin `challenge`
    (CONFIRMED → the shown value; CORRECTED → the corrected value), confidence `MEDIUM` until a dataset or a
    second family agrees.
- **Matching rules (dataset row → variant)**, pure code in `acquisition/gold/domain/match.py`, rules named so a gold
  value carries its rule:
  1. `make`: dataset make normalised through `config/makes.yaml` aliases; must equal the variant's make.
  2. `model`: commercial name normalised (lowercase, accents and punctuation stripped, marketing suffixes from
     `config/gold_datasets.yaml: strip_words`) must contain the variant's model tokens.
  3. `fuel`: dataset fuel/fuel-mode mapped to our powertrain (`petrol, diesel, HEV, PHEV, BEV, …`), must match.
  4. `power`: |dataset kW − variant kW| ≤ 1 kW when the variant already has a power; otherwise power is the
     discriminating key and the row group must be unique for the other keys.
  5. `years`: registration year inside the variant's generation years (`config/generations.yaml`).
  6. `mass` (tie-break only): running-order mass within 3 % when several groups remain.
  - Rule names: `exact` (1–5 and a single group) → confidence `HIGH`; `by_power` (1, 3, 4, 5, model fuzzy) →
    `MEDIUM`; anything with several groups whose values differ beyond the attribute tolerance → **no gold** (the
    dataset cannot tell variants apart). The value of a group is the registration-weighted median.
  - Conversions are declared, not guessed: EU "mass in running order" includes a 75 kg driver → `curb_mass =
    m_running_order − 75` (rule `eu_running_order_minus_driver`); RDW `massa_rijklaar` likewise; RDW
    `massa_ledig_voertuig` is not used (definition differs by registration era).
  - Gold contradicted by ≥ 2 independent families within tolerance of each other and outside the gold tolerance is
    flagged (`flagged=true`, reason) and not used as a signal until the owner or a newer dataset version clears it
    (spec edge case "gold disagrees with all sources").
- **Rationale**: official, free, broad coverage of the EU fleet for the attributes that matter most (power, mass,
  consumption, electric range) — exactly the values that went wrong in the 2026-11-05 chats.
- **Alternatives**: scraping manufacturer configurators as gold (terms, JS, volatility); the EU type-approval
  certificates (not open in bulk); the full EEA CSV download every month (gigabytes for data aggregated by a query).

## R4. Replay design

- **Decision**: `python -m automind.acquisition.replay` (contract: `contracts/replay-cli.md`).
  - Inputs: `--reader km77@v2` (a stored version) or `--reader-spec path.json` (a candidate not yet stored, as the
    gates use it), or `--extractor extract_specs@v4 [--model …]`; `--since 30d` or `--from/--to`; `--domain`;
    `--json`.
  - Corpus: `page_snapshots` with `replayable`, in the period, whose URL matches the parser's `domains` +
    `url_patterns`, joined to the variants the page was judged relevant for (`page_snapshots.variant_ids`, filled
    from `page_relevance`/evidence when the page was used).
  - Pipeline per page: decompress blob → parser interpreter (pure, `acquisition/parsing/interpreter.py`) → rows →
    the same pure validation as live (`sense`, `sense_ev`, units, plausibility via `acquisition/pipeline/validate.py`
    pure functions) → normalised values → compare with gold of that variant (`acquisition/domain/replay.py`).
  - Metrics: `pages`, `pages_with_fields`, `fields_per_page`, `yield` = accepted values / page, `pass_rate` =
    accepted / read rows, `gold_covered`, `gold_match`, `accuracy` = match / covered, `accuracy_lb` (Wilson),
    `mismatches[]` (url, snapshot id, attribute, ours, gold, gold rule, quote).
  - Offline guarantee: readers are pure functions over bytes; the CLI constructs no search, fetch or LLM port, and
    installs a socket guard (`acquisition/replay/offline.py`: patches `socket.socket.connect` to raise) for the run.
    Tests assert the guard and that no `llm_calls` row appears.
  - Extractor replay needs model calls by definition: it runs only in the worker with the agent's budget, caches
    outputs in `extraction_cache(prompt_hash, model, blob_sha256) → output jsonb` so a second replay of the same
    version is free, and is limited to `replay.extractor_max_pages` per run.
  - Performance target (SC-001): ≤ 5 min for 30 days. Pure parsing is ~10 ms per page; at ~30,000 pages the cost is
    dominated by decompression and DB reads — read in batches of 500, decompress in a process pool if needed.
- **Rationale**: one code path for live and replay (the interpreter and validation are the same pure functions), so
  a replay result predicts live behaviour.
- **Alternatives**: replaying through the full async pipeline with fake ports — slower and drags the database
  writers in; recording parser outputs instead of pages — cannot evaluate a new version.

## R5. `acquire()` contract and the strangler steps

- **Decision**: `automind.acquisition.api` is the only engine module the chat may import (contract
  `contracts/acquire.md`): `acquire(AcquireRequest, emit) -> AcquireResult` for research, plus read-model queries
  (`status`, `missing_critical`, `ev_counts`, `powertrains`, `last_done`, `registry_done`, `unmet_areas`,
  `gearbox_families`), `recheck_value()` for challenges, and identity helpers (`lineup()`, `versions()`,
  `generation_hints()`). **Live acquisition runs in the calling process** (inside the user's turn, within its
  deadline and budget, as today); the worker does background work only. Rationale: a user turn must not wait on a
  queue, and the spec's edge case requires the chat to work with the worker down.
- **Strangler steps** (one commit each; `uv run pytest tests/golden` and `scripts/check.sh` green after each; every
  step deletes the moved code from `application/research.py`, which only shrinks):
  - **S0 Facade**: `acquisition/api.py` with the request/result models; `acquire()` calls
    `application.research.run_job` unchanged; read-model functions delegate. `orchestration/nodes/research.py`,
    `nodes/understand.py`, `nodes/compute.py` and `application/resolve.py` (gearbox families) switch to the API.
    New import contract `chat-uses-acquire-only` with the orchestration side already clean.
  - **S1 Plan** → `acquisition/pipeline/plan.py`: `_plan`, `PLAN_MARKETS`, `queries_for`, `registry_queries`,
    `identity_of`, `market_names`, `area_markets`, `known_makes`, `_ai_queries`/`QueryProposals`,
    `learned_sites`/`_learned_cfg` (kept until US7 deletes them). `VERSION = "plan@1"`.
  - **S2 Locate** → `pipeline/locate.py`: `_rank_hits`, the search half of `_collect`, `favourite_priority`,
    `_skipped`, `NO_FAVOURITE`, `WARRANTY_PAGES`, and `_search_pages` as `locate()` returning ranked URLs, url→market
    and independent URLs. `VERSION = "locate@1"`.
  - **S3 Fetch** → `pipeline/fetch.py`: the page half of `_collect` (`fetch(urls, limit, area) -> pages, stats`);
    `infrastructure/pages.py` and `infrastructure/fetch.py` move to `acquisition/infrastructure/` (re-export shims
    left in `infrastructure/` only for `adapters.py` until S8). `VERSION = "fetch@1"`.
  - **S4 Parse** → `pipeline/parse.py`: `_read_tables`, `ReadingRow`/`SiteReading` use, `application/extraction.py`
    → `acquisition/pipeline/extract.py`, site readers → `acquisition/parsing/` (legacy reader kept as the v1
    interpreter until US4). Relevance (`_relevance_target`, `_PageJudge`, `_store_relevance`,
    `MAX_LLM_RELEVANCE_PER_JOB`) → `pipeline/relevance.py`. `VERSION = "parse@1"`, `"relevance@1"`.
  - **S5 Validate** → `pipeline/validate.py`: `_sense_before`, `_sense_ev_before`, `_refile`, `_check`,
    `_sense_after`, `_litres`, `_plausibility_ctx`, `_variant_gearbox`, `fuel_of`, `re_diesel_suffix`,
    `_known_values`, `_ReaderClaim`, `VALIDATOR_REJECTS`, `MONEY_ATTRS`, the validator call; public names (no
    leading underscore) because `recheck_value()` uses them. `VERSION = "validate@1"`.
  - **S6 Persist + merge** → `pipeline/persist.py` (`_evidence`, `_persist`, `_persist_reading`, `_spec_claims`,
    `_items` and all per-area writers `_maintenance … _used_prices`, `_Counter`, `_num/_int/_date`,
    `interval_km/months`, `USED_RANGE_MAX_RATIO`, `_brand_fact_ok`) and `pipeline/merge.py` (`reselect`,
    `fill_gearbox`, `_without_price_outliers`, `_interval_from_schedule`, `accepted_gearboxes`, `mixed_families`).
    `VERSION = "merge@1"`.
  - **S7 Job + market areas + read model** → `pipeline/job.py` (`JobSpec`, `JobResult`, `run_job`, `_run`,
    `_run_market`, `_record_registry`, `_record_learned`, `_mark_run`, `_job_metrics`, `_merge_stats`,
    `_reason_key`, `_used_urls`, `_variant`, `area_hits`, `_area_met`, sources helpers, `_brand_positioning`,
    `current_plan`), `application/incentives_research.py` → `pipeline/market.py`, read-model queries →
    `acquisition/read.py`. `application/challenge.py` and `repair.py` call `acquisition.api.recheck_value` instead of
    private research functions. **`application/research.py` is deleted**; its two `ignore_imports` lines in
    `.importlinter` go and `FROZEN_LEGACY_IGNORES` drops by 2.
  - **S8 Identity readers**: the search/fetch/web-reader parts of `application/lineup.py`, `application/versions.py`
    and `application/resolve.py` (`_web_hints` style helpers) move behind `acquisition.api.lineup()`,
    `versions()`, `generation_hints()`; `Ports.search`, `Ports.pages`, `Ports.readers` leave the chat's `Ports`
    (they live in `acquisition/ports.py`). The forbidden contract then lists `automind.infrastructure.search`,
    `…fetch`, `…pages`, `…site_readers` for `automind.application` and `automind.orchestration` with no
    exceptions (FR-006, SC-004).
- **Rationale**: the order follows the data flow, so each step moves one cohesive block with its callers inside the
  engine already; goldens catch any change; the facade first means the chat stops depending on internals on day one.
- **Alternatives**: one big move — no way to bisect a golden failure; moving pure domain modules (`search_plan`,
  `relevance`, `sense`, `plausibility`, `evidence`, `specs`) into the engine — not needed: they are pure, shared, and
  the chat's compose step reads `evidence`/`specs`; they stay in `automind.domain`.

## R6. Worker process and the Postgres queue

- **Decision**:
  - Process: `python -m automind.acquisition.worker` from the same image; compose service `worker`
    (`command: ["python", "-m", "automind.acquisition.worker"]`, same env files, `depends_on: postgres healthy`, no
    published ports except its metrics on the compose network `worker:9101`). `scripts/dev.sh` starts it next to the
    API (`--no-worker` to skip).
  - Queue table `acq_tasks` (data-model): `kind, dedupe_key UNIQUE, payload, priority, run_at, state, attempts,
    max_attempts, lease_until, locked_by, last_error, result, created_at, started_at, finished_at`.
  - Claim (one statement, `FOR UPDATE SKIP LOCKED`):
    ```sql
    UPDATE acq_tasks SET state='running', locked_by=:w, started_at=now(), attempts=attempts+1,
           lease_until=now() + make_interval(secs => :lease)
    WHERE id IN (SELECT id FROM acq_tasks
                 WHERE (state='queued' AND run_at <= now())
                    OR (state='running' AND lease_until < now())       -- reclaim a dead worker's task
                 ORDER BY priority, run_at LIMIT :n FOR UPDATE SKIP LOCKED)
    RETURNING *;
    ```
    Success → `done` + `result`; failure → `queued` with exponential back-off (`run_at = now() + 2^attempts min`) or
    `dead` after `max_attempts`; long tasks extend their lease every `lease/3`.
  - Scheduling without a second table: a scheduler coroutine enqueues periodic tasks with a period-scoped dedupe key
    (`rollup:2026-11-05`, `drift:2026-11-05`, `prefetch:2026-11-05T06`), `INSERT … ON CONFLICT (dedupe_key) DO
    NOTHING`; periods and hours in `config/acquisition.yaml: schedule`. Event-driven tasks (parser doctor on drift,
    shadow step after a live job, blame judge on a disputed value) use keys like `doctor:km77@v1`.
  - Concurrency: `worker.concurrency` (default 2) tasks at once, own LLM concurrency (`worker.llm_concurrency: 2`)
    so background calls never starve user turns of provider rate limits; all spend counted in the daily cap.
  - Heartbeat: `acq_workers(id, host, started_at, beat_at, version)` every 15 s; Prometheus exporter in the worker
    (`prometheus_client.start_http_server(9101)`) with `automind_worker_beat_timestamp_seconds`,
    `automind_acq_tasks{kind,state}`, `automind_acq_task_duration_seconds{kind}`; a rule `WorkerDown` fires when the
    beat is older than 2 min. Prometheus gets a second scrape job.
  - What moves out of `api/app.py`: `registry_loop`, `insight_loop` and `metrics_loop` (DB snapshot gauges) become
    worker tasks (`registry_review`, `insight_run`, `metrics_snapshot` every minute, exported by the worker). The app
    keeps `retention_loop` and its live process counters (FR-008).
  - Prefetch: task `prefetch` hourly; selects the variants most asked in 30 days (`research_jobs` grouped by
    variant, weighted by distinct chats), areas whose freshness ends within 48 h, runs `acquire(need=REFRESH)` within
    `prefetch.eur_per_day` and `prefetch.jobs_per_run`; marks results like any research run.
- **Rationale**: XIII requires a separate process and a database-backed queue; Postgres `SKIP LOCKED` is the
  standard pattern and adds no infrastructure (X).
- **Alternatives**: Celery/RQ + Redis — new infrastructure; `pg_cron` — extension, logic in SQL; LISTEN/NOTIFY —
  optional later for latency, polling every 2 s is enough; keeping the loops in the API — violates XIII and SC-005.

## R7. Honest reputation: signals, Thompson sampling, promotion

- **Decision**:
  - Accuracy signals without the user (FR-010), weights in `config/registry.yaml: weights`: `gold` 1.0, `challenge`
    1.0, `bad_source` 1.0, `replacement` 0.7, `physics` 0.5, `agreement` 0.3. Agreement counts once per **family**
    (`families` map + `sources.family`): a value confirmed by k independent families gives each capability one
    signal, mirrors in the same family give none to each other (spec US3 AS-3).
  - New score input `signals_w` (decayed sum of signal weights, priors excluded) on `capabilities`; **promotion
    requires `signals_w ≥ lifecycle.promote.min_signals` (default 5)** in addition to attempts/acc_lb/yield
    (FR-012). Lifecycle stays pure in `registry/domain/lifecycle.py`.
  - Ordering for research (autonomy on): deterministic for active sources by `acc_lb × yield − λ·cost`;
    **exploration** chooses which candidate (and which uncertain active source) gets a slot by Thompson sampling:
    for each, sample `a ~ Beta(prior_r + right_w, prior_w + wrong_w)` and `y ~ Beta(1 + accepted, 1 + attempts −
    accepted)`, sampled score `a·y − λ·cost`; the top `candidate_slots` by sample are tried. The RNG is seeded with
    `hash(job_id, area)` so a job is reproducible (III). Budget: `explore.eur_per_day` (counted from attempts by
    candidates), after which no exploration slots are given that day.
  - Searches per accepted value: a daily roll-up `acq_daily(day, area, market, searches, pages, accepted_values,
    cost_eur)` from `search_calls`, `registry_attempts` and claims; gauge `automind_searches_per_accepted_value{area}`
    (SC-009).
  - Baseline: `kpi_baselines(name, started_at, ended_at, values)`; a worker task records the accuracy KPI (share of
    shown values with a wrong signal, by area), satisfaction index, coverage (nodata share) over ≥ 7 days of live
    + prefetch traffic with `autonomy: false`; the admin page shows it; **`registry.autonomy` is switched to true by
    the owner only after the baseline row exists** (T-task with an explicit owner gate).
- **Rationale**: priors and yield dominated the 010 score; with one user, user signals are rare. Gold, families and
  physics give accuracy evidence on every job.
- **Alternatives**: UCB — deterministic but needs tuning of the bonus; ε-greedy — wastes budget on known-bad sources.

## R8. Physics checks

- **Decision**: pure `acquisition/domain/physics.py`, thresholds in `config/physics.yaml`; each check returns
  `Inconsistency(check, values involved, expected range, outlier attribute)`:
  1. `power_mass_accel`: 0–100 time vs kg/kW, envelope table by powertrain and drivetrain (min/max seconds per
     kg/kW bucket), fitted once by code from gold + `eval/reference_vehicles.yaml` and stored in the YAML (a person
     reviews it); outside the envelope by > 15 % → inconsistent.
  2. `torque_power`: for combustion engines, `P[kW] ≤ T[N·m] × rpm_max / 9549` with `rpm_max` from config by fuel
     (petrol 7,500, diesel 5,000); a torque below the minimum the power implies → the torque is the outlier (the
     2026-11-05 "engine-only torque" case for hybrids: system power with engine torque).
  3. `bev_range_energy`: `battery_kwh × 1000 / range_km` within the Wh/km band of the class (120–300) and within
     15 % of the stated Wh/km when present.
  4. `co2_consumption`: WLTP CO2 g/km ≈ `23.8 × l/100 km` (petrol), `26.4 ×` (diesel), ±8 %.
  5. `displacement_geometry`: `π/4 × bore² × stroke × cylinders` within 3 % of displacement.
  6. `top_speed_power`: top speed ≤ `(2·η·P / (ρ·CdA))^(1/3)` with assumed CdA by body class (assumption, IV) +25 %
     slack — only flags gross outliers.
  - Outlier choice: the value whose removal makes the set consistent; if several, the one with the fewest
    independent families behind it; ties → no signal. The signal goes to the outlier's claim (kind `physics`,
    verdict wrong, weight 0.5) with vector blame (R9).
- **Rationale**: III — deterministic, testable; catches the class of errors seen live without any user.
- **Alternatives**: an LLM "sanity check" — not deterministic, forbidden for numbers.

## R9. Vector blame

- **Decision**: pure `acquisition/domain/blame.py` (replaces `registry/domain/blame.py`, which becomes a re-export):
  `blame_vector(case) -> dict[Component, float]` (shares sum to 1) with components `source`, `relevance`, `parser`
  (version), `extractor` (prompt version + model), `units_sense` (rule id), `fusion`. Rules in order, first match
  decides (shares 1.0 unless stated):
  1. `fusion`: the claim itself was right (matches the truth within tolerance) but the selected value was wrong →
     fusion.
  2. `relevance`: the page's relevance verdict was `UNCERTAIN`/`MULTI_VARIANT`, or the claimed value equals gold of a
     sibling variant of the same model (another engine/trim) → relevance; if the right value is also on the page,
     0.5 relevance / 0.5 parser-or-extractor.
  3. `units_sense`: a number in the excerpt converts to the truth under another unit or meaning known to the unit
     layer (PS↔kW, kgf·m↔N·m, engine vs system power/torque from `sense.yaml`) → units_sense with the rule id.
  4. `parser`/`extractor`: the truth (in any accepted unit) occurs in the snapshot text or excerpt → parser
     (`producer=reader`, with `producer_version`) or extractor (`producer=extractor`, version + model).
  5. otherwise `source`.
  - **Disputed** cases (rule 4 fires only on the raw page but not near the attribute's label, or the truth is a
    gold value with `MEDIUM` confidence): enqueue a `blame_judge` task — a web-reader LLM role (no tools; page text in
    `<untrusted_document>`) answers `{component, quote}` from a closed list; accepted only if the quote occurs in the
    snapshot (`evidence.occurs`), plus a re-run of the current parser version on the snapshot; then the vector is
    written. Budget `agents.budgets.blame_judge`.
  - Only components with share > 0 receive `weight × share`: sources in `capabilities`, the others in
    `component_reputation(kind, key, right_w, wrong_w, decayed_at)` (`parser:km77@v4`, `extractor:extract_specs@v3|
    gemini-3.1-flash-lite`, `rule:sense.engine_vs_system_torque`, `fusion:merge@1`). `truth_signals` gains
    `blame_vector jsonb` and `component`.
- **Rationale**: FR-011 — only the blamed component's reputation changes; code decides the obvious cases, the LLM
  only judges disputes with a verified quote.
- **Alternatives**: a single blame label (010) — loses the split cases; LLM-only blame — not reproducible.

## R10. Parser specification schema and v1 migration

- **Decision**: Pydantic model `acquisition/parsing/spec.py` (contract `contracts/parser-spec.md`),
  `model_config = ConfigDict(extra="forbid")`:
  - `reader: str` (`^[a-z0-9_]+$`), `version: int ≥ 1`, `domains: list[str]` (registrable domains, each must be a
    registry source that is not blocked), `url_patterns: list[str]` (optional; anchored regexes, ≤ 200 chars, no
    back-references or nested quantifiers — validated by a small checker against catastrophic backtracking),
    `page_type: Literal["spec_table"]`,
  - `layout: Literal["table", "divrow", "dl", "css"]` with `row_css`, `label_css`, `value_css` required for `css`
    (validated by compiling with selectolax),
  - `fields: list[FieldRule]` where `FieldRule = {attribute ∈ specs.ATTRS, label?: str, prefix: bool = False,
    css?: str, jsonld?: str (dotted path into JSON-LD, e.g. "vehicleEngine.enginePower.value"), unit?: str (must be
    known to the unit layer), prefer_unit?: str, text: bool = False}`; exactly one of `label`, `css`, `jsonld`,
  - `min_rows: int = 3`, `skip_values: list[str] = ["-", "No disponible"]`, `notes: str ≤ 500`.
  - The interpreter (`acquisition/parsing/interpreter.py`) is fixed code written by a person; a spec only fills its
    parameters. **No expression language, no code** (FR-020).
  - v1 migration: `acquisition/parsing/migrate_v1.py` converts each `config/site_readers.yaml` entry (`pairs` →
    `layout`, `labels` → `fields` with `label`, `prefix`, `unit`, `prefer_unit`, `text`) into `ParserSpec(version=1)`
    and inserts `parsers` + `parser_versions(status=active)`. Equivalence test: on `tests/fixtures/html/*` and on
    stored snapshots, the v1 interpreter returns exactly the rows `read_pairs` returned (FR-015, US4 AS-1). After the
    migration the YAML is read only by the seeder; the readers load active versions from the database
    (`acquisition/parsing/registry.py`, cached, refreshed every 60 s and on change).
  - Readers still run only for sources whose terms were checked: the spec's domains must be `access=ok` in the
    registry (replaces `tos_checked`); `auto_data` migrates as `status=retired` (deny-listed).
- **Rationale**: XII allows agents to change parser specifications; a closed schema makes every proposal checkable
  before any gate.

## R11. Structure fingerprint

- **Decision**: pure `acquisition/parsing/fingerprint.py`: parse the raw HTML with selectolax; for every element that
  holds a field label of the spec (or, for drift on unknown pages, every `tr`/`dt`/`div.row`-like repeating block),
  take its tag path from the nearest ancestor with an `id` or up to depth 6 (`table>tbody>tr>td`), class names with
  digits and hashes removed; shingles = set of `(path, label-normalised)` plus the sorted list of label texts found in
  label positions. `structure_hash` = sha256[:16] of the sorted shingles; similarity = Jaccard of shingle sets. A
  day's fingerprint per parser version = the most frequent hash of the day + its shingle set.
- **Rationale**: an early sign of a redesign before yield drops (US4 AS-3), cheap and deterministic.

## R12. Drift statistics

- **Decision**: worker task `drift` daily (and `parser_daily` roll-up first): per parser version and day,
  `pages, fields_total, fields_per_page, rows_read, rows_accepted, pass_rate, zero_pages, structure_hash,
  structure_sim` (vs the 30-day reference set). Drift when, with ≥ `drift.min_pages_7d` (default 15) pages:
  - `fields_per_page_7d < (1 − drift.yield_drop) × fields_per_page_30d` (default drop 0.3), or
  - `pass_rate_7d < pass_rate_30d − drift.pass_drop` (default 0.15), or
  - `structure_sim < drift.min_similarity` (default 0.6) on the latest day — even without a yield drop,
  - and **at once**, outside the daily task: 5 consecutive pages of a version with zero fields (counted by the live
    reader adapter, persisted in `parser_versions.zero_streak`) → `status=degraded` immediately and a
    `parser_doctor` task enqueued.
  - Drift sets `parser_versions.status = degraded`, `degraded_reason`, raises `automind_parser_drift{reader}`,
    journals an `acq_changes` row by `author=system`, kind `parser_status`, and enqueues the parser doctor. A
    degraded version keeps running (its values still pass validation) unless a replacement is accepted.
  - Low traffic: the prefetch reads favourite spec pages of popular variants, which feeds the statistics.
- **Rationale**: FR-016 — three detectors for three failure shapes (slow decay, redesign, sudden break).

## R13. Agents (LangGraph), roles, budgets, levers

- **Decision**: small graphs in `acquisition/agents/`, run as worker tasks; each has a model role in
  `config/models.yaml`, a daily budget in `config/agents.yaml` (human-only, read never written), a max number of runs
  per day, and output that is a Pydantic proposal validated against the lever's schema before any gate. All LLM
  roles here are **web readers** (no tools, page text inside `<untrusted_document>`); context is assembled by code.

| Agent | Trigger | Graph (nodes) | Role / model | Lever (declarative only) |
|---|---|---|---|---|
| scout | daily per gap (area×market with no-data outcomes or < min active) | gaps → queries (code templates) → search → admission (existing) → url-pattern learner (code) → propose | `scout` (query wording only, never sees pages) | `sources`/`capabilities` rows (discovered → admission), `capabilities.url_patterns` |
| parser doctor | drift / zero streak / active spec site without parser | corpus (new-structure snapshots + gold) → draft spec (LLM sees HTML skeleton + labels + gold values, not instructions) → validate schema → self-replay (≤ 3 iterations, feedback = mismatches) → propose | `parser_doctor` | new `parser_versions` row |
| rule auditor | daily: rejected values later confirmed by ≥ 2 families (reject_rule, attribute) clusters ≥ N | cluster (code) → propose keyword/threshold within bounds (LLM explains, code bounds) → propose | `rule_auditor` | `rule_overrides` (whitelisted key paths of `sense.yaml`, `plausibility.yaml`, relevance keywords; bounded change ≤ 20 % per step) |
| extractor tuner | extractor accuracy or yield falls (replay/daily), or a model change in `models.yaml` | failure examples (snapshots + gold mismatches) → propose prompt edit (diff on the current version) or model from the allowed list → propose | `extractor_tuner` | `prompt_versions` (extract_* only), `role_model_overrides` (extractor/validator/relevance, models in `agents.yaml: allowed_models`) |
| evaluator | daily + after each gate step | code only, no LLM | — | none: KPIs, gate decisions, canary steps, rollbacks |
| blame judge | disputed blame (R9) | one structured call | `blame_judge` | none (writes a blame vector) |

  - Hard rules in code (`acquisition/agents/levers.py`, tested): a proposal can only target objects of its own lever
    kind; never `sources.yaml: denylist`, robots/terms fields (`sources.access`, `access_evidence`), budgets, frozen
    sources, prompts of the chat (`interpreter`, `reporter_*`, `hub`, …), code or any file (the 010 no-file-writes
    test is extended to `acquisition/agents`).
  - Budgets start at: scout €0.10, parser doctor €0.20, rule auditor €0.05, extractor tuner €0.20, blame judge €0.05
    per day (total €0.60, inside `DAILY_CAP_EUR`), owner-adjustable in YAML only.
- **Rationale**: XII; small graphs keep each agent testable with fake LLMs (IX); LangGraph is already the project's
  orchestration library.

## R14. Gates

- **Decision** (pure decision functions in `acquisition/domain/gates.py`, thresholds in `config/agents.yaml: gates`):
  1. **Replay** on stored snapshots + gold (corpus: the object's pages of the last 30 days; for a redesign, pages
     after the structure change for yield and every gold-covered page for accuracy). Pass if: `gold_covered ≥
     min_gold` (default 20; otherwise `insufficient_evidence` → the proposal waits while prefetch gathers pages, up to
     7 days, then is abandoned); KPI `accuracy_lb(new) ≥ accuracy_lb(old) − 0.01`; at least one target metric better
     (`yield +0.05` absolute, or `accuracy +0.02`, or `pass_rate +0.05`); guards: coverage (attributes found per
     variant) not lower by > 2 %, cost per accepted value not higher by > 10 %, freshness unchanged. For a proposal
     on a degraded object (old yield ≈ 0) the KPI comparison uses gold accuracy of the new version alone ≥
     `min_accuracy_lb` (default 0.8).
  2. **Shadow**: both versions run on the next N live/prefetch pages of the object (N = `shadow.min_pages` 20, or 3
     days, whichever first; run by the worker on the snapshots the live job just stored — no added latency); the user
     sees the old version's values. Same criteria as replay on the shadow pages; `abandoned` if the budget or 7 days
     run out.
  3. **Accept**: the new version becomes active; the old one `superseded` (kept for rollback).
  4. **Watch** (default 7 days): the evaluator compares daily metrics and wrong signals blamed to the new version with
     the pre-change baseline; rollback on `accuracy_lb` drop > 0.03, yield drop > 20 %, or ≥ 3 wrong signals blamed
     to it; rollback = re-activate the previous version, journalled.
  - One change per object (`unique (object_kind, object_key) where status in (proposed, replay, shadow, watch)`); an
    object under another agent's canary cannot be proposed on; a reverted change's `diff_hash` is not proposed again
    for that object without newer evidence (`created_at > reverted_at` of a snapshot or signal); owner "forbid
    similar" writes `change_blocks(object_kind, object_key, lever, until)`.
- **Rationale**: FR-018 and XII's gate list; numbers chosen so the simulated redesign (SC-007) passes within a day
  using replay + prefetch.

## R15. Change journal: extend `registry_changes` or a new table

- **Decision**: **new table `acq_changes`** for gated declarative changes (and drift status changes), with
  `acq_experiments` for canary metrics; `registry_changes` stays the journal of source status/order changes (its
  revert endpoint and Sources tab are unchanged). The admin **Changes** tab reads both through one endpoint
  (`GET /api/v1/admin/changes`) that unions them into one shape (`origin: registry|engine`). Registry changes
  proposed by the scout still go through the registry's own `limits.check` and land in `registry_changes`, with a
  `change_id` link in `evidence` when an agent proposed them.
- **Rationale**: `registry_changes` has no versions, gates, metrics or explanation; widening it would put nullable
  gate columns on every source change and touch 010's working revert logic.
- **Alternatives**: one generic table with a migration of 010's rows — more risk for no user-visible gain.

## R16. Spec 010 leftovers (US7)

- T059: `PlannedSource.unverified` already exists; `pipeline/persist.py` writes `evidence.unverified`
  (new column), selection counts an unverified family as 0.5 towards `research_plan.minimum_met`, the API payload
  carries `unverified`, `frontend/src/components/badges.tsx` shows "unverified source".
- T060: replacement signal in `merge.reselect` (a selected value replaced by a more confident one → `replacement`
  wrong for the old claim's capability, blamed by R9) and agreement signals per family in the roll-up — done inside
  US3.
- T065: discovery = the scout (US5).
- T067: `JobResult.tried` (domain + outcome per attempted source) → the composed "no data" item → `DataPanel.tsx`.
- T075: delete `domain/learned.py`, `LearnedSourceRepo`, `Ports.learned`, `learned_sites`, `_record_learned`; keep
  the `learned_sources` table (drop in a later spec); `config/search.yaml: learned` removed.
