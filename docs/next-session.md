# Next session: start here (state on 2026-11-06)

Read this first, then `docs/adr/ADR-032-acquisition-engine.md` and `README.md` ("Acquisition engine").
Older handoffs: `docs/history/next-session-until-2026-11-06.md`. Specs 001–009: `docs/baseline.md`.

## 1. What AutoMind is now (compressed specs 010 + 011)

- **Chat** (LangGraph turn graph, `orchestration/`, `application/`): understands the request, identifies cars, asks,
  reports. It orders data ONLY through `acquisition.api.acquire()` (import contract `chat-uses-acquire-only`).
- **Acquisition engine** (`acquisition/`, constitution 1.3.0 XII/XIII): pipeline stages plan → locate → fetch →
  relevance/parse → validate → persist/merge (`acquisition/pipeline/*`, each `<stage>@1`); raw page snapshots (zstd,
  30/180 days, 5 GB); producer versions on every value; gold values from EEA CO2 / OBFCM / RDW + confirmed challenges;
  `python -m automind.acquisition.replay --reader km77@v1 --since 30d` (offline accuracy vs gold).
- **Source registry** (DB, seeded from `config/sources.yaml` + `config/registry_seed_survey.yaml` ≈ 290 sites): honest
  reputation (gold/agreement/physics/replacement signals, vector blame, Wilson lower bound, promotion needs ≥ 5
  accuracy signals and acc_lb ≥ 0.70, Thompson sampling), admission (deny-list/classifieds, robots, quoted terms).
  **`registry.autonomy: false`** until the owner decides (see §3).
- **Worker** (compose service `worker`, `acq_tasks` Postgres queue): metrics snapshot, insight run, registry review,
  reputation signals, parser daily metrics + drift, prefetch of popular cars (€0.30/day, hourly 06–22 UTC), agents.
- **Agents behind gates** (only declarative data, never code/deny-list/robots/budgets; budgets `config/agents.yaml`,
  €0.60/day): parser doctor, rule auditor (thresholds + relevance stop phrases, e.g. the "manuales" class), extractor
  tuner, evaluator (KPIs, rollback), scout (new sources for gaps). Gates: offline replay on snapshots + gold → shadow
  → accept → watch → automatic rollback; journal `acq_changes` with a one-sentence explanation.
- **Insight** (`insight/`): turn outcomes, one feedback table, issue queue with code/config fix proposals →
  "copy for Claude Code" (code fixes stay human).
- **Admin** `/admin` (ADMIN_TOKEN in `.env.docker`): Top problems, Sources, Parsers, Changes, Accuracy (drill-down to
  the page quote), engine status strip. **Prometheus** :9090 (jobs `automind`, `automind-worker`, 17+ rules).
- **Deploy**: `scripts/deploy.sh up --monitoring` (app :8090 because :8080 is UniFi; keys in `.env.docker`);
  move/export/import: `docs/deploy.md`.

## 2. Work in progress — resume here

**Home-market research is merged and deployed (PR #81).** Live replay 2026-11-06 of "я вот выбираю между Deepal S09
и Lixiang L9 и хочу сделать однозначный выбор" with "find missing data" (chat a5fbdff4, €0.29: 164 LLM, 178 searches):
Chinese queries ran and found data (Deepal S09: CLTC range 220 km, charge-sustaining 5.6 l, 0–100 4.9 s from
chexun.com; Li L9: power, 0–100, charge-sustaining 6–7.8 l from 42how/ifeng/ithome/carnewschina…). The market note
"в Европе не продаётся — нашёл на рынке Китая" is shown.

**Done 2026-11-06 (PRs #83, #84, deployed, data repaired after a backup):**
- EREV electric consumption ESTIMATE = battery kWh ÷ CLTC range × 1.4 (+ climate/motorway, + charging losses), only
  from a battery and a range read on ONE page (one version), none outside 11–30 kWh/100 km (`energy._ev_kwh`,
  `compose._cltc_pair`). PHEV battery plausibility 5–80 kWh (EREVs are stored as PHEV). Repair re-checks
  REJECTED_IMPLAUSIBLE too. Live plain turn (chat ccd5f7d8, €0): Deepal S09 28.1 kWh/100 km (40.18 kWh ÷ 220 km,
  chexun), €6.42/100 km at home, 90 % electric.
- `registry_done` ignores runs of an older planner (`stage_versions.plan`): an unmet area is retried at once when
  the planner changed (test `test_registry_done_planner.py`).

**Still wrong (do next):**
1. **Li L9 mixes two generations** (it was not a system/engine power label problem): the variant is "1st Gen
   (2022–, no end) Pro 1.5T EREV AWD", but pages of the 2026 L9 (420 kW, 72.7 kWh, CLTC 420 km) are accepted
   beside the 1st gen (330 kW, 42.8/44/52.3 kWh, 215 km). Selected range_cltc = 420 (2026 car), battery 42.8
   (1st gen) → no energy estimate (correctly). Fix needs the owner's call: which L9 a buyer means in Nov 2026
   (likely the current 2026 car) → add `generations.yaml "Li Auto|L9"` (1st gen 2022–2025, 2nd gen 2026–) so the
   resolver picks the current one and relevance rejects the other generation; then repair + replay with "find".
2. Deepal S09: selected battery 53.49 (larger-battery version) while range 220 belongs to 40.18 — the energy pair
   is right, the spec table shows the other version's battery; max_power missing ("missing power, weight").
3. Remaining items in `docs/wip-home-market-research.md` (graph test, CLTC filing unit tests, market on the
   version row for prefetch, electrive robots/terms).
Verify live after each fix (replay the chat above) and show the owner the report first.

## 3. Owner decisions pending

1. **Autonomy (011 T078)**: baseline `pre-autonomy` runs since 2026-11-05 18:11 UTC. On/after 2026-11-12:
   `docker compose exec app python -m automind.acquisition.reputation.baseline close --name pre-autonomy`, review
   `/admin` Accuracy + Changes, then the owner decides `registry.autonomy: true` (backend/config/registry.yaml).
2. **Physics check**: review the `fit_physics` envelope before enabling power–mass–acceleration (`config/physics.yaml`).
3. **Used prices in Europe**: no open source allows robots; candidate solution = user-pasted listing (009 FR-033).

## 4. Next candidates (after §2)

1. Live test set of 10–15 typical comparisons (new/used, ICE/HEV/PHEV/BEV, EU and China brands) to fill the baseline
   and measure quality (≈ €1–3; estimate first).
2. OBFCM real-world consumption as a yearly worker task (2 GB file).
3. User-pasted listings for used prices.
4. Docs: update `docs/baseline.md` and `docs/deploy.md` for the engine (T126 remainder).
5. Clean old worktrees under `.claude/worktrees/` and merged remote branches.

## 5. Rules that stay in force

- Reply to the owner in Russian. Commit, push and merge to main without review (owner's standing instruction).
- Announce paid live runs with a cost estimate; after a fix, replay the owner's chat live and show the result first.
- Never scrape classifieds; respect robots.txt and terms (a forbidding clause = deny-list); never bypass anti-bot.
- Code, deny-list, robots/terms and budgets are changed only by a person; engine agents change declarative data only
  through gates. Incident fixes go through the engine/issue queue, not by growing chat code.
- Destructive DB changes need the owner's yes and a backup (`scripts/deploy.sh backup`).
- Tests: `scripts/check.sh` must be green; never run two at once on one DB — use
  `TEST_DATABASE_URL=postgresql+asyncpg://automind:$POSTGRES_PASSWORD@127.0.0.1:5433/automind_test_<name>`.
