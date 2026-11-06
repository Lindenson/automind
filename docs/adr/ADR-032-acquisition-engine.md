# ADR-032: Acquisition engine separated from the chat; agents change declarative data behind gates

- **Status:** Accepted
- **Date:** 2026-11-05
- **Spec:** `specs/011-acquisition-engine`
- **Input:** `docs/history/review-2026-11-05-acquisition.md`; constitution 1.3.0 (XII amended, XIII new)
- ADR-031 stays reserved for spec 010's T076.

## Context

The external review of 2026-11-05 (commit 652e691) found a good registry foundation but no acquisition engine:
- search, fetch, extract and validate lived in `application/research.py`, called from chat nodes;
- background loops (registry review, insight, metrics) ran inside the API process;
- nothing kept the raw pages, so a parser change could not be checked against what was fetched before;
- values did not record which reader, prompt or model produced them;
- there was no ground truth independent of the user, so reputation optimised yield, not accuracy;
- spec 010 forbade the system from improving its parsing; `registry.autonomy` was off with no baseline to judge it.

## Decision

1. **A separate engine behind one call.** `automind.acquisition.api.acquire(variant, kind, need, deadline)` is the
   only engine module the chat may import (import contract `chat-uses-acquire-only`). The stages plan → locate →
   fetch → parse → validate → persist/merge → job → identity readers moved out of `application/research.py` one by
   one (strangler S0–S8, goldens g1–g12 after every step); the file is deleted.
2. **A worker process and a Postgres queue** (XIII). `python -m automind.acquisition.worker`, same image, compose
   service `worker` (metrics on `worker:9101`, heartbeat in `acq_workers`). Queue table `acq_tasks` with a unique
   `dedupe_key`; a claim is one `UPDATE … WHERE id IN (…FOR UPDATE SKIP LOCKED)` statement, the candidate select in
   a `MATERIALIZED` CTE so the planner cannot re-evaluate it per row; expired leases are reclaimed, failures back
   off exponentially, then `dead`. Periodic tasks are enqueued with period-scoped dedupe keys (no second table).
   Registry review, insight, metrics snapshots, prefetch, roll-ups, drift, retention and the agents run there;
   stopping `app` does not stop background work.
3. **Raw snapshots in Postgres.** `snapshot_blobs` (content-addressed by SHA-256, zstd level 10, `STORAGE
   EXTERNAL`) and `page_snapshots` (one row per fetch). Identical bodies are stored once. Retention classes
   `accepted` ≥ 180 days, `plain` ≥ 30 days, `pinned` for running experiments; a size cap (`snapshots.max_gb`,
   default 5) deletes expired, then oldest plain, then old accepted, never pinned. JS-only, refused and paywalled
   pages keep metadata only (`replayable=false`).
4. **Producer versions on every value.** Claims and attempts carry `producer`, `producer_version`, `model` and
   `snapshot_id` as plain text identifiers (no foreign keys), so measurement did not wait for parser versions.
5. **Gold values** from open datasets: EEA CO2 (cars), EEA OBFCM (real fuel use), RDW (Dutch register, optional
   `RDW_APP_TOKEN`), the reference set and confirmed challenges; `gold_datasets` + `gold_values` with origin, date,
   matching rule and confidence. Matching keys on make, model, fuel, power ± 1 kW and generation years; an
   ambiguous group gives no gold.
6. **Replay offline.** `python -m automind.acquisition.replay --reader km77@v1 --since 30d` runs the same pure
   interpreter and validation over stored snapshots and reports yield, pass rate and accuracy against gold, with a
   socket guard: zero network and model calls.
7. **Declarative parser specs with drift.** A closed Pydantic schema (`acquisition/parsing/spec.py`), stored in
   `parsers` / `parser_versions`; v1 migrated from `site_readers.yaml` with a proven-equal interpreter.
   `parser_daily` records fields per page, pass rate and a structure fingerprint; slow decay (7d vs 30d), a
   fingerprint change or a zero streak marks a version degraded.
8. **Agents change only declarative data, behind gates** (XII). Scout, parser doctor, rule auditor and extractor
   tuner are small LangGraph graphs in the worker with daily budgets set by the owner; each may only propose its own
   lever: `parser_versions`, `prompt_versions` (extraction prompts), `role_model_overrides` from an allowed list,
   bounded `rule_overrides`, source and capability rows. Never code, files, budgets, the deny-list or robots/terms
   fields. Every proposal passes **replay → shadow → accept → watch → rollback** (pure functions in
   `acquisition/domain/gates.py`); the evaluator is code with no LLM. One change per object; the journal
   `acq_changes` keeps the diff, evidence, before/after metrics and a one-sentence explanation. The owner can revert,
   freeze or forbid similar changes from the admin **Changes** tab.
9. **Autonomy gated by a baseline.** `registry.autonomy` stays `false` until a 7-day baseline
   (`python -m automind.acquisition.reputation.baseline start|status|close --name pre-autonomy`, table
   `kpi_baselines`) is closed and user-independent accuracy signals exist; then only the owner switches it on.
   Reputation uses gold, family agreement, physics checks and replacement signals, blame as a vector (only the
   blamed component changes) and Thompson sampling within an exploration budget.

## Consequences

- One deployable, two processes. `scripts/deploy.sh` and `docs/deploy.md` cover the `worker` service; snapshots
  travel inside the database dump.
- Storage grows by about 25–30 MB/day at the outside, bounded by the cap.
- Every parser, prompt or model change can be measured offline in seconds before anyone sees it, and every
  automatic change is journalled and reversible.
- A user turn never waits on background work; the worker has its own LLM concurrency and its spend counts in
  `DAILY_CAP_EUR`.
- More tables (migrations 0018–0025) and more import contracts to keep.

## Alternatives considered

- **Celery/RQ with Redis, or `pg_cron`**: new infrastructure or logic in SQL; `SKIP LOCKED` adds nothing new.
- **Snapshots as files (WARC, `.html.zst`) or object storage**: a second store to back up and move, no
  transactional link to claims.
- **gzip**: 20–30 % larger and slower than zstd.
- **Foreign keys from claims to parser versions**: would have forced parser versions before measurability.
- **LLM-written parser code**: not reviewable or provable; forbidden by XII. Agents draft declarative specs only.
- **Extending `registry_changes`**: it has no versions, gates or metrics; `acq_changes` is new and the admin tab
  reads both.
- **Turning autonomy on directly**: no baseline to tell an improvement from noise.
