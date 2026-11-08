# Next session: start here (2026-11-08 after S9.4a turn runner; next: S9.4b, then A4c)

**First task: refactoring — spec 012, executed by `specs/012-refactoring/tasks.md` (one phase = one PR).**
No new features until it is done (owner, 2026-11-06). All functional work in §4 is parked, still valid, and
resumes after the refactoring.

Owner's bar (memory "refactoring clarity criterion"): maximum clarity of what happens, zero spaghetti, patterns,
architecture — self-check every PR against it.

Context to read first: `specs/012-refactoring/{spec,plan,research,data-model}.md`, `contracts/code-shape.md`
(use case = class with `run()`; service = ports in constructor + `run()` listing named stages; stages pure;
fallbacks = strategies behind a Protocol), then `tasks.md` from S7 on.
What the system is: `README.md` ("Acquisition engine"), `docs/adr/ADR-032-acquisition-engine.md`,
`docs/history/next-session-2026-11-06-engine.md` §1, specs 001–009: `docs/baseline.md`.

## 0. Resume acquisition A3 (next action)

**Where we are (2026-11-08, main = A4b merged, PR #124).** Chat services S7–S9c-2 are done. Since S9.3 (PR #116):
rule `storage` (sqlalchemy / `shared.infrastructure.db` outside an `infrastructure/` package, **any** directory) and
module limit **200**, both in the ratchet. Owner's decision: acquisition A1–A8 **before** S9d (tasks.md "S9.3"), one
PR per package, each leaving **0 `storage`, 0 `size`, 0 entries** in its package.

Done: **A1 `reputation/`** (PR #117, −30), **A2 `gates/`** (PR #118, −81), **A3a `pipeline/` storage** (PR #120,
−29: every SQL behind `PipelineStores` in `pipeline/infrastructure/`, records/rules in `pipeline/domain/`,
`ValueSelection` replaced `merge.py`, stages get stores via `AcqPorts.stores`), **A3b job as stages** (PR #121, −23:
`ResearchJob.run()` = opening → search → `stages/car_pages` | `stages/market_pages` → `stages/book`; `contracts.py`,
`scope.py`, `home_market.py`; `AcqPorts.shadow` replaced the lazy gates import, contract `pipeline-knows-no-gates`),
**A3c `parsing/`** (PR #122, −70: `readers/` — spec / spec_check / regex_safety, interpreter, fingerprint,
`ParserRegistry` over `ports` (`ParserBook`, `ReadingLog`, `ReadShadow`, `ParserStoreUnavailable`) + `tally`;
`infrastructure/` — `ParserStore`, reading_log, v1_specs (YAML, deny-list, seed), `wiring.live_readers()` /
`parser_registry()` / `yaml_registry()`; `extraction/` — contracts, areas, extract; `normalise/` — cell_value, labels,
text, fuel, gearbox, numbers). **pipeline and parsing: 0 entries.**
**A4a `registry/`** (PR #123, −67: `domain/` config (`RegistryConfig`), records (`CapabilityView`, `ReviewedCapability`,
…), planning (rank_queryable / ordered_active / pick_candidates), review (`plan_review`), seed_rules over
`SurveyEntry`/`Favourite`; `application/` ports (one `RegistryStoreUnavailable`), `RegistryService`, `SiteAdmission`,
`DailyReview`, `RegistrySeed`; `infrastructure/` one store per port + `wiring` (`registry_service`, `signal_store`,
`site_admission`, `daily_review`, `registry_seed`), repo.py gone; `delivery/registry.py` (startup seed),
`delivery/cli/registry.py` (`python -m automind.delivery.cli.registry seed | review --once`); contract
`registry-services-over-ports`). **registry: 0 entries.**
**A4b `gold/` + `identity_readers/`** (PR #124, −56: gold `domain/` records (`StoredGold`: no ORM row leaves the
store), text, config (`MatchCfg`, `GoldRules`), match, reference, choice; `application/` `GoldLoad` with the strategies
`DatasetGold` / `ReferenceGold`, `ChallengeGold`, ports (one `GoldStoreUnavailable`); `infrastructure/` gold_store
(`GoldStore.best`), candidate_store, loaders (rdw split, `ApiDataset`, `ReferenceFile`), wiring; CLI
`delivery/cli/gold.py`. `identity_readers/`: `web` (was pipeline/identity.py), `domain/registered`,
`DatasetVersions` over `VersionBook`/`LiveRows`, version_store, wiring; `AcqPorts.datasets: LiveRows | None`; contract
`gold-services-over-ports`). **gold, identity_readers: 0 entries.**
Structure baseline 1534 (after S9.4a), mypy report (all src) 195, 14 import contracts. Owner confirmed the A3 split (a → b → c) on
2026-11-08; A4 is split the same way (one PR per package): A4a registry → A4b gold → A4c snapshots/drift/replay.

**The template (follow it for A3–A8; `reputation/` and `gates/` show it):**
- `domain/` — plain records (frozen dataclasses: no ORM row reaches a rule) + pure functions; verdicts stay pure.
- `application/` — services (class, ports in the constructor, public methods read as named steps), `ports.py`
  (Protocols; one `<Area>StoreUnavailable`; split `measure_ports`-style when > 200 lines); every module docstring
  names the errors and what happens on each.
- `infrastructure/` — every SQL; stores map rows → records; `translate_errors(<Area>StoreUnavailable)` from
  `shared/infrastructure/db/errors.py`; `wiring.py` builds the services (callers use `wiring.x()`).
- A table is read by its owner (`scripts/table_owners.yaml`; rule `sql` catches it); a port joining areas the
  contracts keep apart is wired in `delivery/` (e.g. `delivery/baselines.py`, worker handlers injected via
  `entry.run(…, handlers)`). CLIs → `delivery/cli/`.
- Private helpers of another package used from outside → make them public there (A2: `replay/run.load_variants`, …),
  never `noqa: SLF001`.
- Unit tests over fakes for every service: one failure path at least (store down, lost claim, budget, no measure).
- Safety tests are never weakened (A2: `test_no_self_change` flagged `self.budgets` → renamed `agent_budgets`).

**S9.4 States, not words (owner 2026-11-08, on `chat/dialog/runner.py`).** Rules `word` (a state/kind/verdict
compared with a string literal), `errtext` (an exception recognised by its text), `duck` (getattr/hasattr capability)
in `scripts/structure_states.py`; contract code-shape.md "States, not words"; pr-self-check item **States**.
Baseline 1225 → 1557 (+332), PR #125. **S9.4a done** (PR #126): `chat/domain/turn.py` (TurnStatus, JobStatus,
PresetKind, Role, TRANSITIONS, check_move), `chat/dialog/turn/` (entry `route()` table, endings table, journal,
execution, replies, outcome), runner 423 → 160; one provider-failure classifier `shared/contracts/provider_failure.py`
instead of five word lists; structure 1534. Next: **S9.4b** the finished acquisition packages (94 entries) → A4c. From A4c on each package step also leaves 0
`word`/`errtext`/`duck`.

**Then A4c** — `snapshots/`, `drift/`, `replay/`
(run 359; 33 entries) and A3b-f1 (type `Found.stats` / hits: `SearchStats` / `SourceHit`). Gold readers use `gold/infrastructure/wiring` (`gold_store().best(vid)`, `gold_rules()`); registry callers use
`registry/infrastructure/wiring` (scout gets a `SiteAdmission`, blame judge `signal_store()`). Callers of the parser store use
`ParserStore()` (drift/daily, gates/page_reading) or the lazy imports still listed for agents/replay — A4/A6 remove
them. Then A5 worker, A6 agents, A7 engine top level + `admin_api.py` (1049) → `admin/`, A8
`acquisition/domain` modules over 200 + `infrastructure/fetch.py`. Then S9d (chat: `confirm.py` nodes, `ask.py` →
questions service, `ChallengeValue`, `report/stages/verdict.py` → `ResearchHistory`), S10, S12 rest, S13–S15.
Deploy checkpoint after 2026-11-12.

Gate per step: check.sh, then (never in parallel) diff_behaviour, check_checkpoints; PR (body = pr-self-check.md,
answered); merge; update this §0. Never edit files while diff_behaviour runs (it checks out base/head in the tree).

### Workflow per step (what worked S3a–S7)

```bash
set -a; . ./.env.docker; set +a   # POSTGRES_PASSWORD; .env.docker has no TEST_DATABASE_URL, so for a bare pytest:
export TEST_DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:5433/automind_test"
scripts/check.sh > $SCRATCH/check.log 2>&1        # ruff, format, mypy strict scope, lint-imports (13), structure ratchet, pytest, vitest
python3 scripts/refactor/diff_behaviour.py --base origin/main --head HEAD   # (not executable) base→head→base, PYTHONHASHSEED=0; must end "differs 0"
cd backend && uv run python ../scripts/check_checkpoints.py      # read-only prod: 0 module paths in blobs, threads load
```
- Moves: `scripts/refactor/move.py <map.yaml>` (maps in `specs/012-refactoring/moves/`; whole packages first);
  after moves `scripts/check_structure.py --write-baseline` only if the count did not grow.
- Structure ratchet baseline `scripts/structure_baseline.txt` (1225 now: +storage, size 200; A1 −30, A2 −81, A3a −29, A3b −23, A3c −70, A4a −67, A4b −56); new violations fail
  the gate; a PR shrinks the entries of every package it touches (pr-self-check.md).
- Migration tests fail with "tables can have at most 1600 columns" → the scratch DB `automind_mig` is worn out by
  roundtrips (dropped columns count): `docker compose exec -T postgres dropdb -U automind automind_mig && … createdb …`.
- Never run two test runs on one DB at once. Commit → push → `gh pr create` → `gh pr merge --merge` → delete
  local+remote branch; update this file's §0 at the end of each step.

## 1. State when parked

- main = A4b merged (PR #124). **Production still runs the pre-012 code** (`2b5eb92`, PRs #83–#85,
  `scripts/deploy.sh up --monitoring`, app :8090). Deploy policy: none before the baseline closes on 2026-11-12; then
  the first 012 checkpoint (compose worker command is `python -m automind.cli worker`), live replay of chat ccd5f7d8
  after it, then deploys only at S9, S12, S15.
- Last gate (A4b): `check.sh` green — 1579 backend passed (2 skipped) + 161 frontend; 14 import contracts kept
  (+`gold-services-over-ports`); structure 1225/1225 new 0; mypy report 195 (gold, identity_readers in strict).
  Behaviour diff vs previous main: differs 0 (same 58, unstable 24, racy 7). check_checkpoints: 529 blobs, 0 paths, 12 threads. Never start pytest while
  diff_behaviour runs (same test DB). If a session dies during diff_behaviour:
  `git worktree remove --force /tmp/behaviour-*/{base,head}`, `git worktree prune`.
- Kept as it was (A3b), worth a look later: the shadow gate's feed of a job also gets the pages relevance dropped
  (`PageTally.shadow_pages`, the old filter `outcome_by_url.get(url)`); harmless for the comparison, but it reads like
  an accident.
- Repo hygiene: no worktrees, no feature branches local or remote.
- Last live check (pre-012): chat ccd5f7d8 (Deepal S09 vs Li L9) — S09 energy computed (EREV estimate), L9 "no data".
- Backup before the last data repair: `backups/automind-20261106-100212.sql.gz`.

## 2. Refactoring — goal and rules

Goal: the same behaviour with less code and fewer places to look. Not a rewrite.

Rules:
- Behaviour unchanged: goldens and `check.sh` green after every step; one step = one PR, merged to main.
- No DB schema change without a migration and the owner's yes (destructive → backup first).
- Import contracts (`lint-imports`, 10 contracts, e.g. `chat-uses-acquire-only`) stay kept; tighten, never loosen.
- Start with an inventory and a written plan (spec `012-refactoring` via speckit, or a short plan in this file),
  show it to the owner, then execute in small steps.

Inventory hints measured on 2026-11-06 (verify, then extend):
- Size: `backend/src` ≈ 45k lines, tests ≈ 22k. Largest modules: `application/compose.py` 1228,
  `infrastructure/db/models.py` 1202, `acquisition/admin_api.py` 1049, `domain/casefile.py` 804,
  `domain/intake.py` 786, `application/identify.py` 721, `orchestration/nodes/compute.py` 714,
  `infrastructure/db/repositories.py` 698, `application/resolve.py` 642. `compose.py` mixes report assembly,
  DB reads (`load_car`) and TCO input building.
- Leftovers of the spec 011 move into `acquisition/`: 17 modules say "moved from … unchanged" — check for
  duplicated or dead paths in `application/` (`repair.py`, `research` remnants) and thin re-export layers.
- 843 `# fmt: skip`, 107 `type: ignore` (mostly `acquisition/api.py` `_engine(...)` returns) — the facade typing
  can be fixed once instead of per call.
- Powertrain: EREV exists in the domain/energy but identity stores EREVs as `PHEV` (`resolve.py` Literal) —
  decide one representation (it caused the 40 kWh plausibility rejection).
- Config: 31 YAML files in `backend/config` (registry_seed_survey.yaml 4.9k lines); check for unused keys and
  defaults duplicated in code (e.g. `prefetch.py` repeats `acquisition.yaml` defaults).
- Repository hygiene: 31 worktrees in `.claude/worktrees/`, 75 remote branches (most merged), 89 local branches;
  root `sec.md` (initial foundation spec of 002 — move to `docs/history/`); `backups/` 25 MB local only.
- Docs: `docs/baseline.md` and `docs/deploy.md` not yet updated for the engine (T126 remainder); review files
  `docs/review-*.md`, `ux-audit-*.md`, `sources-revision-*.md` — archive what is closed.
- Test DB for parallel runs: `TEST_DATABASE_URL=…/automind_test_<name>` needs `automind_mig_<name>` too
  (migration tests replace `/automind_test` by `/automind_mig`).

### 2a. Refactoring plan — superseded by spec 012

**Current plan: `specs/012-refactoring/` (spec, clarifications, plan with steps S0–S15).** The table below is the
first inventory, kept for its measurements.

#### First inventory (2026-11-06)

Measured: src 44.9k / tests 22.4k lines; all 31 YAML files are loaded; all 90 local and 75 remote branches are
merged; the "moved from" modules have no old copies left (sources `application/research.py`,
`incentives_research.py` are gone) — the real debt is layer leaks and large mixed modules.

| # | Step (one PR each) | Risk |
|---|---|---|
| R0 | Hygiene: remove 31 worktrees, merged local+remote branches; `sec.md`, closed `review-*`/`ux-audit-*`/`sources-revision-*` → `docs/history/` | none |
| R1 | Dead code: functions with zero callers (`by_rule`, `version_number`, `same_model_generations`, `compose.completeness`, `selected_values`, `_legacy_basis`, `criteria._normalize`, `all_settled`, `removal_notice`, `_domain_from_url`, …); one-off `repair.py`/`backfill.py` if already applied | low |
| R2 | Config = one source: drop code copies of YAML defaults (`worker/prefetch.py`, `worker/config.py DEFAULTS`, `snapshots/codec.py`, `search.yaml intake.*` repeats in lineup/versions/identify, feasibility, outcome, …); `locate.py` default 8 vs `search.yaml` 6 → YAML wins; unread keys removed | low |
| R3 | Typed facade: `acquisition/api.py` `_engine()` → typed lazy imports, −15 `type: ignore` | low |
| R4 | `compose.py`: DB reads (`load_car`, `tco_car`, `evidence_refs`, `persist_computations`) → infrastructure behind a port; pure car facts → `application/car_facts.py`; report blocks → `application/report_blocks.py`; delete compose from `.importlinter` ignore list | medium |
| R5 | `resolve.py`: DB access → `infrastructure/variant_repo.py`, pure matching → `domain/variant_match.py`; tighten `.importlinter` | medium |
| R6 | `orchestration/nodes/compute.py`: pure helpers (case facts, period totals, verdict extras, …) → application | medium |
| R7 | Mechanical splits with re-exporting `__init__`: `db/models.py`, `db/repositories.py`, `admin_api.py` → packages; `casefile.py` (delta apply), `intake.py` (7 clusters, fix duplicate `_NUM` :181/:564), `identify.py` (fallback, ladder) | low–medium |
| R8 | New contract: `acquisition.pipeline` must not import `application`/`infrastructure.db` (now `pipeline/relevance.py:14-17`) | low |
| R9 | Docs: `baseline.md`, `deploy.md` for the engine (T126 remainder) | none |

Owner questions: (a) EREV as its own powertrain in identity (`resolve.py` Literal + data migration of known
EREVs from `PHEV`) — this changes behaviour and data, so a separate step after R9 or later; (b) delete remote
branches too, or local only; (c) `# fmt: skip` ×843 — leave as is (proposal) or normalise in a separate PR.

## 3. Owner decisions pending (unchanged)

1. **Autonomy (011 T078)**: baseline `pre-autonomy` runs since 2026-11-05 18:11 UTC. On/after **2026-11-12**:
   `docker compose exec app python -m automind.acquisition.reputation.baseline close --name pre-autonomy` (pre-012 code in production; after the 012 deploy: `python -m automind.cli baseline close --name pre-autonomy`), review
   `/admin` Accuracy + Changes, then the owner decides `registry.autonomy: true` (backend/config/registry.yaml).
2. **Physics check**: review the `fit_physics` envelope before enabling power–mass–acceleration (`config/physics.yaml`).
3. **Used prices in Europe**: no open source allows robots; candidate = user-pasted listing (009 FR-033).
4. **Li L9 generation**: which L9 a buyer means in Nov 2026 (proposal: the current 2026 car; add
   `generations.yaml "Li Auto|L9"` 1st gen 2022–2025 / 2nd gen 2026–).

## 4. Parked functional backlog (after the refactoring, in this order)

1. Live test set of 10–15 typical comparisons (new/used, ICE/HEV/PHEV/BEV, EU and China brands) to fill the
   baseline before the autonomy decision and measure quality (≈ €1–3; estimate first, owner's yes).
2. OBFCM real-world consumption: the loader exists (`acquisition/gold/infrastructure/loaders/eea_obfcm.py`,
   `config/gold_datasets.yaml eea_obfcm`, 2024 collection ≈ 2.1 GB CSV) but was never loaded (gold_values has only
   eea_co2 and rdw rows) and the energy model does not read it. Make it a yearly worker task, then use the fleet
   l/100 km (and PHEV grid kWh) as the car's `consumption_real` when a group matches (make, model, fuel, kW,
   year, ≥ 10 vehicles), labelled "real-world, EU fleet OBFCM".
3. User-pasted listings for used prices (if decision §3.3 is yes).
4. China-market leftovers: Li L9 generation mix (§3.4, then repair + replay with "find"); Deepal S09 spec table shows
   the 53.49 kWh version's battery and lacks max_power; graph test for the market note and `market="CN"` jobs;
   unit tests for CLTC filing / Chinese units / `Aliases.names_of`; `Variant.market` at `upsert_variant`;
   electrive.com robots/terms (details: `docs/history/wip-home-market-research.md`).

5. Found by the spec 012 behaviour diff (2026-11-06): the report's order of criteria with equal weights (e.g.
   ownership_cost and reliability, both 6.2) depends on Python's hash seed (set iteration), so it can differ
   between runs for the user. Fix after the refactoring: a stable tie-break (criterion key).
   Same diff: the order of engine options offered for a model (Kia Sorento "288/265/215 CV" vs "215/265/288 CV") and
   of sources in a block varies between runs (DB reads without ORDER BY / job completion order). Fix: explicit order.
   And `tests/graph/test_limit_pause.py` is timing-dependent (scripts/refactor/racy_tests.txt): make it deterministic.
   `tests/integration/test_catalog_merge.py` failed once in a full run (A4a), 6/6 alone: which duplicate is kept
   depends on row order — give `repair.merge_duplicates` an explicit tie-break.

## 5. Rules that stay in force

- Reply to the owner in Russian. Commit, push and merge to main without review (owner's standing instruction).
- Announce paid live runs with a cost estimate; after a fix, replay the owner's chat live and show the result first.
- Never scrape classifieds; respect robots.txt and terms (a forbidding clause = deny-list); never bypass anti-bot.
- Code, deny-list, robots/terms and budgets are changed only by a person; engine agents change declarative data only
  through gates. Incident fixes go through the engine/issue queue, not by growing chat code.
- Destructive DB changes need the owner's yes and a backup (`scripts/deploy.sh backup`).
- Tests: `scripts/check.sh` must be green; never run two at once on one DB.
- Live replay driver: WebSocket `ws://127.0.0.1:8090/ws/chat/{id}`, cookie from `GET /api/v1/chats`, send
  `{"type":"hello","last_seq":0}`, then `user_message`; confirm with `{"type":"confirm","choice":"yes",…}`;
  "find it" = `{"type":"find","focus_cars":[],"areas":[]}`. Keep the script in the session scratchpad.
