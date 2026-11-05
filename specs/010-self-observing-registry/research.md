# Research: Spec 010

Decisions taken from the code as it is on 2026-11-05 and the owner's boundary (spec Context).

## R1. Served model and prompt version per call

- **Decision**: keep `llm_calls.model` (already the served model: `llm_gateway._build(role, name)` attaches `UsageCallbackHandler(role, name, …)` per fallback model); add `primary_model` (= `model_name(role)`), `fallback` (bool), `prompt_name`, `prompt_version` (parsed from the first-line comment `<!-- prompt: interpreter v2 … -->`), `prompt_hash` (sha256[:12] of the system text). `structured()` sets a contextvar with the prompt identity before `_with_fallbacks`; the callback reads it.
- **Rationale**: no change to call sites; the gateway is the single LLM entry (VII).
- **Alternatives**: pass prompt identity through every call site (many edits); store only the hash (version label is what a human reads).

## R2. Relation of a message to the previous answer

- **Decision**: add `relation: Literal["continues","rephrase","correction","complaint","thanks","new_topic"] = "continues"` to `Interpretation`; rules + 6 few-shots in `interpreter.md` (version → v3). The runner writes it onto the *previous* turn's outcome (`relation_next`).
- **Rationale**: zero extra calls (spec FR-002). `request_kind=critique` and `correction` already exist; `relation` is orthogonal (a correction of a car vs "you misunderstood me").
- **Alternatives**: a separate cheap classifier call (cost, latency); text heuristics (weak across ru/es/en).

## R3. Turn score

- **Decision**: pure `domain/outcome.py`: `classes(facts) -> set[FailureClass]`, `score(rating, signals, weights) -> float`. Explicit rating r → (r−1)/4. Otherwise start 0.6, add configured weights (`config/outcome.yaml`): thanks +0.3, continues +0.1, report reached +0.1; rephrase −0.4, correction −0.3, complaint −0.5, wrong-data −0.4, bad-source −0.3, process failure −0.5, no-data −0.2, left after answer −0.1; clamp [0,1]. Facts are gathered from existing data: `turns.status/action/limits_reached`, guard logs (`guard.sentences_removed` → count recorded in final state), intake events (`CORRECTED`, `CARD_EDITED`), research "no data" in the composed facts, feedback rows.
- **Rationale**: transparent, testable; calibration by an LLM judge is out of scope (spec Assumptions).

## R4. Feedback unification

- **Decision**: new `feedback` table; writers: `RatingRepo.save` (also writes feedback), `challenge.recheck` (feedback + truth signal; fills `value_challenges.turn_id` = latest DONE turn of the chat, `claim_id` = first claim behind the value), WS `bad_source` (new), runner (complaint/rephrase/correction from `relation`, `critique` request kind). Old tables kept for compatibility.

## R5. Background work

- **Decision**: `insight_loop()` and `registry_loop()` as asyncio tasks created in `api/app.py` lifespan next to `retention_loop()`; each wakes every 10 min, runs its daily job when due (stored in `insight_runs` / `registry_runs` with date) and an early run when ≥ N new failures/feedback since the last run. A Postgres advisory lock per job prevents overlap after a restart.
- **Rationale**: ADR-026 single process; X (no queue). Never touches the per-chat lock.

## R6. Clustering

- **Decision**: deterministic keys, no embeddings. Component/class/key per spec US3:
  - `dialogue/<class>/<request_kind>/<lang>` from `turn_outcomes`;
  - `parser/drop/<reader>/<domain>` when 7-day ok share < 30-day share − 0.2 (from `site_reader_stats`), `parser/zero/...` on a run of empty pages;
  - `relevance/<reason>/<area>` from `page_relevance` rejections whose variant+attribute later got an accepted value from another family;
  - `check/<reject_rule>/<attribute>` from `claims` where the same attribute was later accepted from another family at a close value;
  - `nodata/<area>/<market>` from outcomes with class no-data;
  - `model/fallback/<role>` when the fallback share of a role > 20% over 7 days.
  Fingerprint = sha1 of the key. Threshold per component in `config/insight.yaml`.
- **Rationale**: with few users, explainable buckets beat statistical clustering.

## R7. Diagnosis text

- **Decision**: role `analyst` (already in `models.yaml`), prompt `analyst_issue.md`, structured output `{summary, likely_cause, direction, likely_files[], verify}`; input = key, counts, 5–10 examples (user/assistant text cut, claim excerpts, URLs) and the static component→files map from `config/insight.yaml`. Daily budget `insight.budget_eur` (default €0.30). `likely_files` filtered to existing paths. The copy text is built by pure `insight/domain/issue_text.py` (markdown).
- **Alternatives**: no LLM (only counts) — kept as fallback when the budget is used.

## R8. Kind of data and market

- **Decision**: kind of data = research area (`domain/research_plan.AREAS`: specs, price, used_price, maintenance, reliability, reviews, measured, engineering, manufacturer (incl. warranty), depreciation, used_issues, incentives). Market = query market already tracked in `_rank_hits` (`url_market`). A capability key is `(domain, area, market)`.
- **Rationale**: research already plans and records by area and market; no new taxonomy.

## R9. Score and lifecycle

- **Decision**: per capability, decayed counts (half-life 90 d): `attempts`, `accepted`, `right_w`, `wrong_w`. Yield = (accepted+1)/(attempts+2). Accuracy lower bound = Wilson 95% on `right_w/(right_w+wrong_w)` with a type prior added as pseudo-counts (manufacturer 4:0.5, spec_db 3:1, publication 2:1, forum 1:1, unknown 1:1). Score = acc_lb × yield × prior_weight − λ·cost_per_attempt. Signal weights: gold/challenge 1, bad source 1 (wrong), later replacement 0.7, family agreement 0.3. Blame: if the stored excerpt holds the corrected value → `parser`/`extractor` (issue), not the source.
- Lifecycle thresholds in `config/registry.yaml`: candidate→active at ≥ 8 attempts and acc_lb ≥ 0.6 and yield ≥ 0.2; active→degraded at acc_lb < 0.45 or yield < 0.05 over ≥ 10 attempts, or 0 accepted in last 10; degraded→retired after 21 days; retired re-try 1 attempt per 30 days; candidates get ≤ 1 slot per job (exploration).
- **Rationale**: Wilson + priors are enough for small samples (spec Edge Cases); bandits deferred.

## R10. Admission check and discovery

- **Decision**: admission (pure rules + fetch): deny-list/classifieds markers (`sources.yaml` + survey verdicts) → blocked; robots via the existing fetcher policy for the sample path → blocked per path; terms page found from common paths (`/terms`, `/aviso-legal`, `/impressum`, `/legal`, links with those words), read by role `terms_reader` (web reader, no tools) returning `{forbids_automated: bool, clause: str}`; the clause must occur in the page text (checked by code, as `evidence.occurs`) or the verdict is "unknown" → candidate stays at 0 slots until re-check; readable content = existing extraction gives ≥ N characters without JS. Discovery: open search queries from `queries.yaml` `open` templates per area in the languages of the markets, budget `registry.discovery_eur_per_day` (default €0.20), ≤ 3 per gap per day.
- **Rationale**: reuses fetcher, robots, deny-list, query templates; the survey already shows the verdict shapes.

## R11. Research integration (strangler)

- **Decision**: `acquisition/registry/api.py` exposes `plan(area, markets, variant_make) -> Plan` (ordered domains with priority ints compatible with `favourite_priority`, plus `candidate_slots`) and `record(attempts)`. In `research.py`: `favourite_priority` reads priorities from the plan; `learned_sites` returns active non-favourite capabilities; `_record_learned` → `record()` with richer outcomes (accepted / rejected reason / robots / junk). With `autonomy: false` the plan reproduces today's favourites priorities and learned rule exactly (golden-checked).

## R13. Prometheus as the metrics and alert store

- **Decision**: no metrics tables and no in-app alerting. `/metrics` via `prometheus_client` (new dependency): live counters/histograms incremented at existing write points (turn end, LLM callback, search record, feedback, registry attempt and change, fetch outcome); slow KPIs (satisfaction index per kind/window, accuracy, nodata share, capability counts, per-source score/acc_lb/yield for candidate/active/degraded, open issues, spend, loop heartbeats) computed by a `metrics` loop every 60 s into an in-memory snapshot served by a custom collector (FR-031). Single process → default registry. Names prefixed `automind_`.
- **Alert rules**: hand-maintained `deploy/prometheus/automind-rules.yml` with thresholds as rule constants; `tests/unit/test_prom_rules.py` parses it and checks every metric name used is registered by the exporter (FR-032). Optional compose profile `monitoring` (Prometheus + Alertmanager, pinned images) with `deploy/prometheus/prometheus.yml`; routing left to the owner.
- **Rationale**: owner's decision — the admin page is short (top problems, source quality and changes); history, trends and alerts are Prometheus' job, which it does better.
- **Alternatives rejected**: in-app rollups and alert engine (duplicate of Prometheus); OpenTelemetry (no need now).

## R15. Top problems and configuration levers

- **Decision**: impact = failing turns in 7 days × class severity (process_failure 3, wrong_data 3, not_understood 2, wrong_car 2, no_data 2, bad_text 1, too_costly 1) + 2 × distinct chats; top 10 of open/regression issues. `config/insight.yaml` declares **levers**: per component the configuration files and keys that can fix it (e.g. `check/*` → `plausibility.yaml: by_powertrain.<attr>.<powertrain>`, `sense.yaml: magnitude.<attr>`; `dialogue/*` → `questions.yaml.<KIND>`, `models.yaml.<role>`; `relevance/*` → none, code only; `nodata/*` → `queries.yaml.<area>`). The analyst may propose `kind=config` only with a declared file+key; code validates the key exists in the loaded YAML, else downgrades to `kind=code`.

## R12. Admin UI without a router

- **Decision**: `main.tsx` renders `<AdminApp/>` when `location.pathname.startsWith("/admin")`; the token is entered once and kept in `sessionStorage`, sent as `Authorization: Bearer`. The backend SPA fallback serves `index.html` for `/admin`.
- **Alternatives**: react-router (new dependency, not needed for 4 tabs).
