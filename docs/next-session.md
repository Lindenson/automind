# Next session: start here (2026-11-28: PR #163 point fixes merged, spec 017 drafted — owner decides §H, then IC1)

Three approved specs, one PR per step, merged to main without review; after each merged step that touches `src`:
`scripts/deploy.sh up --monitoring`, replay the owner's chat live (cost ≈ €0.01–0.06; script below), show the
result to the owner first. Spec 012 (A4c onward) waits until 013 S7. New code follows the 012 code-shape contract.

- **013 Dialogue quality** — `specs/013-dialogue-quality/` (source: `understanding-spec.md`, audit: `coverage-audit.md`).
  Decisions G1–G11 approved (G4–G11 on 2026-11-27: understander = cheap fast model, ≤ +20 % p95; topic change =
  goal naming other cars or stop; first goal only at S4, full at S4b; weekly misses script, owner confirms; no
  per-chat switch; ANSWER_AND_REASK always; thresholds after baseline; 014 order kept).
- **014 Node contracts** — `specs/014-node-contracts/` (approved 2026-11-26). C3 with 013 S4, C4 with 013 S5.
- **015 Policy rework** — `specs/015-policy-rework/` (source: `source-spec.md`, audit: `coverage-audit.md`), approved
  2026-11-27 with D1–D11 as proposed; cross-references E1–E10 applied to 013/014 (one owner per thing: the policy
  trace is 015 `policy_decisions`, not 013 `policy_trail`; 013 T041 is written on 015's `Rule`/`Situation`).

**Done**
- 013 S0a (T001–T003) g13–g17 red; **T004** (PR #145) understanding eval set, 148 cases ru 55 / es 46 / en 47
  (`backend/tests/eval/understanding/`; stop cases expect `ANSWER_FROM_CONTEXT` until T041 names a stop action).
- 013 S1 (PR #137), **S2** (PR #142): rejection memory on the car, verify before proposing, tactic change; g13 t2 S2
  checks gate, its stop/settle parts stay strict `later:` known bugs.
- **014 C1** (PR #144): `@node` + typed In/Out for all 32 nodes, owners registry, `contract.md`, differs 0.
  `request_kind` single owner is `apply_delta` (not interpret — see tasks.md T103). Double writers pinned by test,
  each with the step that removes it (C2/C3/C4/015 PL5).
- **015 PL1** (PR #147): rules as classes, `decide(situation, config) -> Decision` with the rule trail, `ROUTES`
  (END/SUSPEND/LOOP), contract `policy-pure`; 10 000-case regression vs the frozen old chain: 0 differences;
  `policy_max_passes` setting (8). Structure 1406 → 1401.
- **014 C2** (PR #148): `ctx.case()` / `ctx.save_case()` (`turn/cached.py` `Cached[T]`, reusable for PL2's
  fingerprint), `save_version(expected=)` → `VersionConflict`, report/answer persist after the model call
  (`DeferredIntake`), one conflict retry in `@node`, a second fails the turn. Structure → 1390.
- Remote branches can no longer be deleted (repo rule GH013): `014-c2-case-once`, `015-pl1-policy-skeleton` stay.
- Pre-prod = main `c22dd39` (redeployed 2026-11-27 ~09:05). Live replay (chat b6c108ab, €0.027): t1 finds the
  **W206 C-Class** (S1 holds), asks Mercedes fuel + CX-60 engine + new/used; t2 ("…отменяй поиск. пошел в жопу")
  is again not a stop and not acknowledged — the same fuel question, and the **CX-60 question vanished** (settled
  silently, bug 8; the remove chip already showed "200 CV RWD Exclusive-Line" on t1).
- Review of the owner's d170b861 continued on 11-27 (turns 5–11): C→E fixed; new findings — (A) intake attempt
  counters stay on car#1 after the model changes, so the C-Class engine was auto-picked by the ask limit ("C 200 d",
  with a false "asked twice" note; `ladder/steps.py:154`); (B) "такой же но более нового поколения" became
  `generation_hint="newer"` and an **invented version "C 200 DSG FWD"** was stored in `vehicle_variants`
  (`f28fe7f7…`, key `…|newer|c 200 dsg|mhev`, source LOOKED_UP) — W206 is already the newest; (C) an engine edit
  on the card was dropped silently ("card edit not applied"; S4 T046); (D) the verdict flipped to "equal" because
  depreciation data was missing. A and B are in no spec yet; the invented row awaits the owner's decision (backup
  first).
- Live miss 2026-11-27 (chat eb81dd90 t2): complaint read as `correction` + unchanged case → "nothing changed since
  the last report" with no report → strict xfail `tests/unit/chat/dialog/policy/test_policy_known_bugs.py` (fix at S4).
- Pre-prod runs main `a2677a8`+ (redeployed after C1); `check_checkpoints.py`: 0 module paths, 17 threads load.

- **013 T005** (PR "T005"): baseline `specs/013-dialogue-quality/baseline.md` (+ `.json`), €1.15, gemini-3.6-flash:
  all fields 20 % vs harness ceiling 17 %; answer 66/72, goals 76/86, reaction 82/100, action 28 = ceiling (the
  harness has no identify/assess: action is indicative); p95 of understanding 4.6 s (G4 reference). Re-run:
  `cd backend && uv run python -m tests.eval.understanding.runner` (DATABASE_URL = test DB for usage rows).
- 013 S5 got findings A/B as I8/I9 (T056/T057, PR #150); the invented row f28fe7f7 stays until T057 (≈ 320
  dependent rows, no cascade); backup `automind-20261127-101515.sql.gz`.
- Spec 016 narration guard drafted from a teammate's source (PR #151, NOT merged): audit, D1–D11 await the owner;
  N1 (quick fixes of the old guard) proposed in parallel with 015 PL2.
- 2026-11-27 ~10:20 Google prepaid credits ran out (402 on every model → pre-prod down); owner topped up ~10:45.

- **013 T006** (PR #153): nightly eval via host crontab (wolper, 03:30, `scripts/eval_understanding.sh`, ≈ €1.15/run,
  usage rows in the pre-prod DB) → `eval-runs/understanding/` → app gauges `automind_understanding_eval_*`; rules
  Stale (36 h) / Errors (> 5). `latest.json` seeded with the T005 run. Pre-prod redeployed at `fb2aa76`.
- Mistake: `git add -A backend` committed the owner's `chat.zip` in #153 (public repo; an old copy of `chat/`
  sources, no secrets found); removed + gitignored in #154, file restored on disk byte-identical. Still in history
  (56d69f3): purging needs a force-push of main — owner's call. Never `git add -A` a directory with chat.zip.
- Spec 016 merged as a draft (#151); D1–D11 approved by the owner on 2026-11-27 as proposed (D3: yes).
- **016 N1** (PR "016-n1-guard-fixes"): old guard fixed — numbers equal at the written precision, metric names cut,
  no figures from engine codes or "€3.550", one sentence splitter (no fragments), topic words for every insight
  attribute, tie winner by aliases, rewrite failures narrowed, answers run all four rules, a quiet removal notice.
  §1 table: 205 hp, "400 €", "4 %", reliability "no data"/"better", "лучший выбор — Prado" now caught; the year as a
  price, words for numbers, ratios/percentages wait for N2. N2–N5 after 013 S7.
- chat.zip purge: owner said yes, but the repo ruleset `safe_main` (all branches: no deletion, no non-fast-forward,
  no bypass) blocks a force-push; the owner disables it for the purge or keeps the file in history. Even after a
  purge, GitHub keeps PR #153's refs (support request to remove cached views).

- **015 PL2** (PR "015-pl2-one-input"): `Ports.policy` built once at startup (`adapters.policy_config`, Decimal money,
  `strict_inputs` = `AUTOMIND_POLICY_STRICT`), `dialog/policy/situation.py` `situation_from` with invariants (cars,
  assessed_version) → log `policy.input_error` + `automind_policy_input_errors_total{field}` (strict in tests),
  fingerprint cached per run (`ctx.last_report_fingerprint()`), assess writes `feasibility_pending` +
  `assessed_version`, node `dialog/nodes/policy.py`. Regression 10 000: 0 differences; behaviour diff 0; structure
  1390 → 1381. Watch the input-error metric on pre-prod for a week before strict (spec 015 acceptance; owner agreed
  2026-11-27: strict after a week at 0, i.e. not before 2026-12-04).
- **015 PL3** (PR "015-pl3-decision-record"): `policy_decisions` + `policy_configs` (migration 0026, owner's yes,
  90 days), `DecisionLog` / `DecisionRepo`, one row per pass, `policy.decided` log, `metrics/policy.py`, alert
  `AutomindPolicyPassLimit`, retention step on the one API task, CLI
  `docker compose exec app python -m automind.delivery.cli.policy why <turn_id> [--replay]` / `export <turn_id>`,
  golden `tests/unit/chat/dialog/policy/golden/`. Decide `max_passes` from `automind_policy_passes_per_turn` two
  weeks after (≈ 2026-12-11, §H D6).

- **013 S3** (PR "013-s3-understanding-shadow"): the new understanding runs in the shadow of the old interpreter on
  every typed turn and button (concurrently, old decides), one row per turn in `turn_understanding` (migration 0027,
  owner's yes, 90 days), metrics `automind_understanding_*`, CLI
  `docker compose exec app python -m automind.delivery.cli.turn show <turn_id>` (understanding + policy passes).
  Switch: `AUTOMIND_UNDERSTANDING_SHADOW=false`. Eval `uv run python -m tests.eval.understanding.shadow` (≈ €0.13,
  flash-lite) → `specs/013-dialogue-quality/shadow.md`: answer 66 → 96 %, goals 76 → 83 %, all but action 49 → 68 %,
  p95 4.6 → 1.6 s. Follow-up (PR "013-s3-understanding-fixes"): owner's goal boundaries, prompt v4, I1 rejection
  check; flash-lite all but action 72 %, gemini-3.6-flash ≈ 77 % (goals 93 %, p95 3.3 s): the model is worth ≈ 4–5
  points — owner decides the understander's model before S4. Owner: watch the shadow rows a few days
  (`turn show`, `automind_understanding_overrides_total`) before S4.
- Pre-prod = main with S3 (redeployed 2026-11-27 ~14:20, backup `automind-20261127-141641.sql.gz` before 0027). Live
  replay of d170b861 (chat 9c891343, €0.024): the old path answers as before (W206 C-Class found; t2 "отменяй поиск"
  not a stop, the CX-60 question vanished: S4 / S5). The shadow on t2 reads goal **stop**, reaction **complaint**, no
  answer (old: critique) — but also a false rejection "MODEL C-Class" with no `wanted` (the car already is the
  C-Class; `heard_rejections` keeps it because only `wanted == current` is dropped). Fix before S4 applies
  rejections from the intent: "you did not find X" while the case shows X is no rejection (prompt + check).
- `diff_behaviour.py --base-db URL`: a head with a new migration leaves the test DB at a revision main does not know
  (every base test errors, "same 0, added N"); give the base its own DB (`automind_test_<tag>` + `automind_mig_<tag>`).

- **Chat 725e7437 (2026-11-28, BMW 320d "not found")** → PR "017-point-fixes-identity": card "not this car" read by
  the interpreter ("320 d" on a BMW → 3 Series, 320d, diesel) and keeps year/mileage/condition; a named version the
  sourced list lacks is searched on its own (`identification/named_version.py`, once per generation, memo
  `looked_for`) before any "not found"; question texts say "not found in the sources", never "has no"; EEA failure
  cached 1 h (empty answer 1 day); `versions.dropped` / `versions.read` log lines. Root causes: model "320 d" from the
  card's word split; versions list = the `versions` reader's 11 rows of one dealer page (caetano.es) that dropped the
  320d row in the live call (7/7 re-runs kept it); bmw.es data pages fetch ERROR since 11-27. Removed the bad
  `model_versions` row (backup `automind-20261128-171624.sql.gz`). Owner: spec 017 = contracts + e2e tests for every
  user interaction, and a source pyramid (registries/maker/big spec DBs first, dealers last).

- Pre-prod = main `a0e30f8` (PR #163, redeployed 2026-11-28 ~17:35). Live replay (chat 6e032fe4, €0.065): "not this
  car → 320 d" → BMW 3 Series G20 diesel 320d ✓; after "BMW 320d 2024 б/у, автомат" the list offers 318d / 320d ✓
  (the 320d is found), chip 320d → "2.0 320d 190 CV", drive → card: C 200 d auto NEW + 320d G20 2024 USED auto
  (research ≈ €0.18 not run). Still wrong: (1) t1 the **old interpreter returned no cars** (only set_depth), the word
  safety net added them without years/models — the shadow understander read both right → 013 S4; (2) "320d" in
  `trim_hint` is not the engine family → asked "318d or 320d?" again; (3) template `rephrase` still says "There is no
  such engine"; (4) gearbox chips offered "manual" for a G20 320d. All in spec 017 IC2 / 013 S4.
- **Spec 017 drafted** (`specs/017-interaction-contracts/`, PR "017-spec"): interaction contracts (table in code,
  socket e2e per row) + source pyramid (tiers 0–3, EEA/DGT/RDW bulk first, dealers never form a list). Owner
  decisions §H1–H6 pending (S4 now with gemini-3.6-flash? order; DGT; VehiclesDB; commercial; purge dealer lists).

**Teammate review 2026-11-27 (owner: "учти критику") — checked against the code, where each point lives**
1. Understanding = one label of 14, word lists before the model, text not by id → 013 S4 (T040–T043); S3 shadow
   measured it (all but action 49 → 72 %). Reviewer's priority #1, same as ours.
2. Guard = heuristics (numbers against a bag of numbers, word lists for contradictions) → spec 016 N2–N5
   (placeholders + structured claims); N1 done. Reviewer puts it #2; today it waits for 013 S7 — owner to reorder?
3. Flat board (~35 keys, manual reset, `SkipValidation` ×89) → 014 C3 T120/T121 (sections, `begin_turn` reset;
   T120 now also: nested values validated, no `SkipValidation`).
4. One process (turn tasks and event subscribers in memory; restart on several replicas would resume a turn twice)
   → in no spec. Backlog: a turn owner with a heartbeat + cross-process events, when a second worker is needed.
5. Known bugs: "переформулируйте" in English (verified: a refused reading drops the language, the turn's is reset to
   "en") and an engine failure in one research job failing the whole round (verified: `_acquire` catches only budget
   and timeout) → fixed in PR "013-point-fixes"; "declined" = "already done" → 015 PL5 (next step,
   `policy/contracts.py` already says so).
6. Noise: spec/FR/chat references ≈ 1850, `# fmt: skip` 1164, `except Exception` 19 in chat (all but two carry a
   reason; the two in `report_writer` and `turn/execution` re-raise what they do not handle) → owner's open question
   §2a (c) (`fmt: skip`); proposal: a 012 step moving the traceability from comments to `docs/traceability.md`.
7. Heavy dialog layer: `phrases.py` 632, `report_text.py` 590, `confirm.py` 484 → 012 S9d (confirm.py split per
   confirmation) + new: the three-language texts into a message catalog (resources), code only looks them up.

**Next (agreed with the owner 2026-11-27)**
1. ~~015 PL1 ∥ 014 C2~~ done. Owner to decide: add findings A (reset attempt counters when a car's model changes)
   and B (a relative generation — "newer", "older", "такой же" — is never a generation name; nothing unverified
   enters `vehicle_variants`) to spec 013 S5; delete the invented row.
2. ~~013 T005, T006~~ done. Owner: D1–D11 of spec 016 and whether N1 goes now.
3. ~~015 PL2, PL3~~ done; ~~013 S3 shadow~~ done. 015 PL5; then 013 S4 + 014 C3 + 015 PL4 (owner first: the
   understander's model, see 013 S3 above).

**Working notes**
- Parallel agents share the session scratchpad: give each its own log names (a `check.log` was overwritten once).
- Parallel agents: each in its own worktree AND its own test DB (`automind_test_<tag>` / `automind_mig_<tag>`, create
  with `docker compose exec -T postgres createdb -U automind <db>`; pass `TEST_DATABASE_URL=…5433/automind_test_<tag>`).
- Live replay script (scratchpad, recreate if gone): GET `/api/v1/chats` for the owner cookie, chat id = a new uuid4
  (there is no POST), WebSocket `/ws/chat/<id>` with headers cookie + `origin: http://127.0.0.1:8090`, send
  `{"type":"hello","last_seq":0}` then `{"type":"user_message","text":…}`, read until `usage`. Do not truncate the
  text (a 900-char cut once looked like a bug). Owner's chat d170b861 messages: `chat_messages` where role='user'.
- Still open in the owner's chat: "отменяй поиск" not a stop (S4); cars settled silently with guessed versions,
  so a later message triggers a report with questions unanswered (bug 8, S5).

The section below (§00) is the history that led to spec 013; §0 and later describe the parked refactoring.

## 00. The agent cannot do its job — FIRST (owner, 2026-11-26)

Owner: "the last chat is the limit of patience… the agent can't do anything". The refactoring (A4c onward) waits:
the dialogue must first stop being confidently wrong. Ask the owner to confirm this order at the start.

**Chat `d170b861` (2026-11-26 19:14): "я выбираю между Clase C Berlina мерседесом и Маздой CX-60".**
1. **"Clase C" became the E-Class.** `shared/vehicle/makes.MakeRegistry.match_model` (called from
   `identification/stages/normalise_name.match_model`): `sound_key("c-class") == sound_key("e-class")` (ratio 100), and
   the same-word-count bonus (+5) lifts that fuzzy 100 to 105, above the `< 100` condition that guards the margin
   check meant for exact names — so a different model is picked as if written exactly (reproduced:
   E-Class 100/105, CLA 90, Clase C 85). The known set had no C-Class because the stored Mercedes-Benz ES line-up
   (`brand_lineups`, 2026-11-26 19:08) is garbage: **one** model, "Clase S", from a news article about S-Class prices.
2. The user's correction ("ты не нашел мерседес класс C") replaced the car → the same path → E-Class again.
3. **"отменяй поиск. пошел в жопу" was not a stop**: classified `correction`, the same E-Class engine question
   repeated. No stop/quit intent exists (bug 10); the complaint went to `feedback` as `correction`, not `complaint`.
4. **Mazda CX-60 silently settled** to "3.3 200 CV RWD Exclusive-Line" on turn 2 without any answer about it (same as
   bug 8, i10 "manual").
5. Self-diagnosis: turn 1 got `wrong_car` + `not_understood` (good), score 0; still no issue below the threshold.

**Diagnosis across 4bb83866 and d170b861**: identification is a stack of heuristics (fuzzy and phonetic matching,
LLM hints as hard filters, a fallback order that reads the user's own evidence last, auto-settling the single
survivor) that guesses with full confidence, never checks the guess against what the user wrote, and never admits
it is unsure. Nothing measures it: no regression suite of real dialogues.

**Plan to propose (owner decides the order):**
- a. **Dialogue regression suite** from the owner's failed chats (4bb83866 MX-30 R-EV + URL, d170b861 C-Class,
  i10 "manual", CX-60 auto-settle, "cancel / go away", complaint during a question) as scripted scenarios with
  recorded search hits/pages; each asserts the car identified and the turn's reply kind; part of `check.sh`.
- b. **Never confidently wrong**: a model name the user wrote is kept unless an exact (or Cyrillic-transliterated)
  match says otherwise — no fuzzy/phonetic jump between distinct models (C→E, CLA); fix the bonus/margin bug;
  the user's words and URL beat the line-up and datasets; a contradiction asks; nothing settles without either the
  user's answer or evidence that names that version.
- c. **Stop, complain, quit** at any step (bug 10), no repeated question (bug 7), a complaint is never parsed as an
  answer (bug 6), no silent settling (bug 8).
- d. **Line-up sanity**: a make's line-up from fewer than N models or from a single news article is not stored.
- e. Then §0a 1–5 and 9 (URL first, EREV, hints, pool, routing, self-diagnosis).

Pre-prod: http://192.168.1.142:8090 runs main `ff93b2f` (up since 2026-11-25). `backend/src/automind/chat.zip`
(untracked, 2026-11-26 16:16) is the owner's — do not commit or delete it.

## 0a. Pre-prod bugs (owner, 2026-11-08) — FIRST, before A4c

Chat `4bb83866` (Mazda MX-30 R-EV vs Hyundai i10; the owner gave the mazda.es R-EV page) — identification never found
the car, and a complaint was taken for an answer. Owner: "my link must be the priority"; "R-EV / EREV is its own
family". Causes found (case_files change log, turn_outcomes, feedback, code):

1. **The user's URL is read last.** `IdentificationService` fallbacks run SourcedVersions → CatalogueRows → OpenWorld;
   only OpenWorld's resolver passes `user_url` to `generation_hints`. SourcedVersions always answered (one dataset
   version), so the page was never opened. Fix: a page the person sent is read first and the version must match it.
2. **No EREV.** `shared/vehicle/engine.Fuel` has no erev, the interpreter prompt says nothing of range extenders: the
   model wrote `fuel: bev` for "R-EV". Decision proposed: EREV a powertrain of its own (fuel vocabulary, interpreter,
   identification, energy; the Deepal/Li EREV-as-PHEV problem is the same), Mazda R-EV its family (rotary generator).
3. **An LLM hint is a hard filter.** `versions.lookup(fuel=…)` → `registered_generation` kept only BEV rows (the EEA
   registers the R-EV as petrol/electric), one version left → settled without asking, although `family: R-EV`
   contradicted it. Fix: the hint ranks, a contradiction asks.
4. **A named version does not rebuild the pool.** After "E-SKYACTIV R-EV 125 kW (170 CV) AT 2WD" the R-EV row was
   created in the catalogue, yet the ladder asked "which engine of the R-EV: EV Prime-Line?" and offered a manual
   gearbox (EV/EREV are automatic only).
5. **Answers routed to the wrong car and language switched**: the Mazda string was taken as the answer to the open
   Hyundai i10 gearbox question ("I did not understand … for Hyundai i10"), reply in English.
6. **A complaint during identification is "not understood"**: "Очень плохо! Ты ничего не нашел" was read as an answer
   to the open engine question; `request_kind=critique` was recognised, but the policy's intake rules run before the
   critique rule, and that rule only reworks an existing report. Fix: acknowledge, never parse a complaint as an
   answer, change tactic (the user's page, the name they gave).
7. **No repeat guard**: the same impossible question asked three times. A repeated question = a dead end: leave it and
   flag the turn.
8. **i10 settled as "manual"** on the complaint turn without an answer — find where the choice came from.
9. **Self-diagnosis would not have seen it**: feedback rows exist (correction, complaint) and scores are low, but no
   signal for "user URL not read" or "user corrected the identified car" (`wrong_car` only on replace_cars/car_edit),
   insight thresholds need 3 per 7 days, and `config/insight.yaml files:` points to paths the refactoring removed
   (identification/identify.py, application/research.py …). Fix: the two signals, a complaint opens an issue at once,
   update the paths and add a gate check that every path there exists.

10. **Complain or quit at any step (owner)**: while the system asks (identification, intake card, choices), the
    user must be able to (a) file a quality complaint and (b) end the dialogue — buttons next to every question,
    not only the report's rating. Both are signals for self-diagnosis: a complaint opens an issue with the turn's
    path and the open question; ending the dialogue during a question ("abandoned at <question kind>") is counted as a
    failure of that step, never as silence.

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
Structure baseline 1433 (after S9.4b), mypy report (all src) 195, 14 import contracts. Owner confirmed the A3 split (a → b → c) on
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
instead of five word lists; structure 1534. **S9.4b done** (PR #127): finished acquisition packages at 0
`word`/`errtext`/`duck`; named states in `acquisition/domain/{gates,versions,claims,truth,tolerance}`, registry
`CapabilityStatus`; structure 1433, mypy report 193. Next: A4c. From A4c on each package step also leaves 0
`word`/`errtext`/`duck`.

**Then A4c** — `snapshots/`, `drift/`, `replay/`
(run 359; their entries incl. word/duck) and A3b-f1 (type `Found.stats` / hits: `SearchStats` / `SourceHit`). Gold readers use `gold/infrastructure/wiring` (`gold_store().best(vid)`, `gold_rules()`); registry callers use
`registry/infrastructure/wiring` (scout gets a `SiteAdmission`, blame judge `signal_store()`). Callers of the parser store use
`ParserStore()` (drift/daily, gates/page_reading) or the lazy imports still listed for agents/replay — A4/A6 remove
them. Then A5 worker, A6 agents, A7 engine top level + `admin_api.py` (1049) → `admin/`, A8
`acquisition/domain` modules over 200 + `infrastructure/fetch.py`. Then S9d (chat: `confirm.py` nodes, `ask.py` →
questions service, `ChallengeValue`, `report/stages/verdict.py` → `ResearchHistory`), S10, S12 rest, S13–S15.
Pre-prod follows main (redeploy after each merged step).

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

- **Pre-production = main** (owner 2026-11-08: "this is not prod but pre-prod; live on the new code that reflects
  the current refactoring"). The old pre-012 stack (`2b5eb92`) is gone; `scripts/deploy.sh up --monitoring` runs main
  (`3373ca0`, PR #127) as project `automind`: app on **0.0.0.0:8090** (`AUTOMIND_BIND=0.0.0.0` in .env.docker; LAN:
  http://192.168.1.142:8090), worker `python -m automind.cli worker`, Prometheus/Alertmanager on localhost. Backup
  before the switch: `backups/automind-20261108-200433.sql.gz`. The owner tests it in parallel and collects bugs;
  **redeploy after every merged refactoring step** (`scripts/deploy.sh up --monitoring`, then a live replay).
- Live check after the switch (2026-11-08): "Deepal S09 vs Lixiang L9" → DONE/REPORT, 26 blocks, €0.0095 from cache
  (first run on a copy of the DB: 42 s, €0.039, L9 now with EREV energy ≈327 km electric — check §3.4 generation).
- Baseline `pre-autonomy` (closes 2026-11-12) ran on pre-012 code until 2026-11-08 19:05 UTC and on 012 code after:
  read its KPIs with that cut in mind before the autonomy decision (§3.1).
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
   `docker compose exec app python -m automind.cli baseline close --name pre-autonomy` (012 code runs since 2026-11-08), review
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
