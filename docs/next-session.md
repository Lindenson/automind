# Next session: start here (parked on 2026-11-07, after S9.1c-1)

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

## 0. Resume S9c (next action)

Done and merged: S0–S8, S9a (T074 characterisation, PR #101), S9b (T076 research service, PR #102).
Services so far: `identification/` (S7), `report/` (S8: ReportService, facts/, blocks/, stages/), `research/` (S9b:
ResearchService create/run_job/conclude, rounds). Ports for the dialog's side: `report.contracts.ReportWording`,
`research.contracts.ResearchWording`/`ResearchEvents` — all implemented by `dialog/report_wording.py` (WORDING) and
the TurnContext; no second port over `acquisition.api`.

**S9.0 done (T074a, owner 2026-11-07):** `chat/application/usecases/challenge.py` is the named antipattern (Any where
the types matter, dict result, DB directly, one 55-line public function, no docstring, no failure handling). Controls
added: API rules `any`/`untyped`/`doc`/`public`/`ignore`/`lazy`/`exempt` (`scripts/structure_api.py`, in the ratchet;
baseline 799 → 1667), contracts/code-shape.md "Public API of a layer", `specs/012-refactoring/checklists/pr-self-check.md`
(copied into every PR body and answered), strict mypy override fixed to the post-S3a modules.

**S9.1a/b/c-1 done (PRs #105, #107, #108):** `research/`, `identification/` meet the bar (strict, 0 API baseline
entries); `report/` is typed and strict (`LoadedCar`, `KeyedCars`, typed `Computed`/`ReportWording`; `JsonObject` in
`shared/contracts/json.py` is the one sanctioned loose type, for UI blocks and config sections — owner to confirm).
Patterns: graph-state shapes are TypedDicts in the service's `contracts.py`; closed sets read through typed maps
(`FUELS`, `GEARBOXES`, `DRIVES`, `INTAKE_ITEMS`) or `Model.model_validate`; `Reference.makes` is the `MakeNames`
Protocol. mypy report over src: 330 → 271.

**Next: S9.1c-2 — report docs and shape** (`grep services/report/ scripts/structure_baseline.txt | grep -E
"^(any|doc|public|ignore)"`): 28 `doc`, 9 `public` (criteria_block, data_panel_block, persist_computations, load_car,
car_facts, insight_values, assemble_blocks, tco_car), 4 `ignore` (car_view._constraints, intake_card._car_edit/
_profile_edit, verdict.limits_from), 8 `any` (car_view edit helpers, criteria breakdown, scores.facts_of, verdict
persona_counterfactual/profile_focus). Then T074b is done. Then:

**S9c — T075 interpretation** (tasks.md "S9"): `chat/dialog/nodes/understand.py` (≈500 lines; fat nodes
interpret_node, apply_delta_node, assess_node).
1. `git switch -c 012-s9c-interpretation`.
2. Safety nets of the text (`_pick`, `_makes_named`, `_make_to_choose_from`, `_charging_from_text`, `_car_named`,
   `_energy_from_text`, `_person_from_text`, `_cars_safety_net`, `_brand_from_text`) → stages of
   `services/interpretation/` (regexes `_REPLACE`, `_OWN`, `_SENTENCE` → `chat/domain/vocabulary` or named constants);
   `_not_understood`, `_pending_answered` → `interpretation/understood.py`; `assess_node` + `_plan` → a service
   (assessment of the cars and the research plan); nodes ≤ 30 lines.
3. Then S9d — T078: `confirm.py` nodes (ask_node, prepare/apply variants, prepare/apply intake) ≤ 30 lines,
   `ChallengeValue` use case + port (← usecases/challenge.py; last `ignore_imports` with repair), purity contracts for
   chat.dialog and chat.application; T077 feasibility is already thin. Deploy checkpoint after 2026-11-12.
Coverage before S9c (characterisation is enough, no new pinning needed): `understand.py` 90 %, `confirm.py` 89 %,
`interpretation/ask.py` 85 %, `interpretation/interpret.py` 95 %, `research.py` 94 %.
Gate per step: check.sh, then (never in parallel) diff_behaviour, check_checkpoints; PR; merge; update this §0.
Then S10 use cases, S11 acquisition pipeline + parsing package, S12 admin/persistence split + contracts, S13
order/API + mypy scope, S14 docs, S15 acceptance.

Known deferred inside 012: nodes still fat (`understand.py` 500, `confirm.py` 465) — S9c/S9d; T019a flaky `test_catalog_merge` (host load) open.

### Workflow per step (what worked S3a–S7)

```bash
set -a; . ./.env.docker; set +a   # POSTGRES_PASSWORD; .env.docker has no TEST_DATABASE_URL, so for a bare pytest:
export TEST_DATABASE_URL="postgresql+asyncpg://automind:${POSTGRES_PASSWORD}@127.0.0.1:5433/automind_test"
scripts/check.sh > $SCRATCH/check.log 2>&1        # ruff, format, mypy strict scope, lint-imports (11), structure ratchet, pytest, vitest
python3 scripts/refactor/diff_behaviour.py --base origin/main --head HEAD   # (not executable) base→head→base, PYTHONHASHSEED=0; must end "differs 0"
cd backend && uv run python ../scripts/check_checkpoints.py      # read-only prod: 0 module paths in blobs, threads load
```
- Moves: `scripts/refactor/move.py <map.yaml>` (maps in `specs/012-refactoring/moves/`; whole packages first);
  after moves `scripts/check_structure.py --write-baseline` only if the count did not grow.
- Structure ratchet baseline `scripts/structure_baseline.txt` (1555 now); new violations fail
  the gate; a PR shrinks the entries of every package it touches (pr-self-check.md).
- Never run two test runs on one DB at once. Commit → push → `gh pr create` → `gh pr merge --merge` → delete
  local+remote branch; update this file's §0 at the end of each step.

## 1. State when parked

- main = S9b merged (PR #102). **Production still runs the pre-012 code** (`2b5eb92`, PRs #83–#85, `scripts/deploy.sh
  up --monitoring`, app :8090). Deploy policy: none before the baseline closes on 2026-11-12; then S3a–S6 go
  together as the first checkpoint (compose worker command is now `python -m automind.cli worker`), live replay of
  chat ccd5f7d8 after it, then deploys only at S9, S12, S15.
- Last gate (S9b): `check.sh` green — 1491 backend passed (2 skipped) + 161 frontend; 11 import contracts kept;
  structure 799/799; mypy report 330 errors; behaviour diff vs previous main: differs 0 (racy 7: limit pause,
  make_to_choose, persistent_thread — unstable between base runs too); check_checkpoints: 470 blobs, 0 paths,
  11 threads. Lesson: never start pytest while diff_behaviour runs (same test DB) — it broke a golden once.
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
   `docker compose exec app python -m automind.acquisition.reputation.baseline close --name pre-autonomy`, review
   `/admin` Accuracy + Changes, then the owner decides `registry.autonomy: true` (backend/config/registry.yaml).
2. **Physics check**: review the `fit_physics` envelope before enabling power–mass–acceleration (`config/physics.yaml`).
3. **Used prices in Europe**: no open source allows robots; candidate = user-pasted listing (009 FR-033).
4. **Li L9 generation**: which L9 a buyer means in Nov 2026 (proposal: the current 2026 car; add
   `generations.yaml "Li Auto|L9"` 1st gen 2022–2025 / 2nd gen 2026–).

## 4. Parked functional backlog (after the refactoring, in this order)

1. Live test set of 10–15 typical comparisons (new/used, ICE/HEV/PHEV/BEV, EU and China brands) to fill the
   baseline before the autonomy decision and measure quality (≈ €1–3; estimate first, owner's yes).
2. OBFCM real-world consumption: the loader exists (`acquisition/gold/loaders/eea_obfcm.py`,
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
