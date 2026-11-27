# Tasks — Spec 013 Dialogue quality

One phase = one PR, merged to main; after each: `scripts/deploy.sh up --monitoring`, replay the owner's chat live
(`docs/next-session.md` §5 driver), show the result to the owner before he tests. Gate per PR: `scripts/check.sh`
green, structure ratchet does not grow, pr-self-check answered (specs/012 contracts still apply to new code:
ports, named stages, enums + transition tables, ≤ 200 lines/module, no SQL outside `infrastructure/`).

Paths below are under `backend/src/automind/` unless they start with `backend/` or `scripts/`.
"(verify)" = the reference was read on 2026-11-26; check it again before editing.

## S0 — Measuring first (PR 1)

The existing harness `backend/tests/golden/` (YAML dialogues, `runner.py`, `schema.py`, replay with scripted model
outputs + cassettes; `-m live` for real models) is the base. Extend it, do not build a second one.

- [x] T001 Dialogue scenarios (replay, scripted model outputs = what the model really returned in the chat, taken from
  `turn_events` `case_file` payloads and the LLM call log): `g13_clase_c_cx60` (d170b861: turn 1 must keep C-Class
  and not settle the CX-60; turn 2 "ты не нашел мерседес класс C. отменяй поиск" must stop), `g14_mx30_rev_url`
  (4bb83866: URL read first, R-EV kept, complaint not an answer), `g15_i10_manual` (no silent "manual"),
  `g16_no_on_card` ("нет" on the intake card never confirms), `g17_question_during_question` ("давай сравним с
  BMW" / "а что такое DSG?" during an open question). Fixture line-up for Mercedes-Benz = the real garbage one
  ("Clase S" only) so the test reproduces the failure.
- [x] T002 Extend `schema.py` expectations: per car `model`, `identity_state` (from S5 on; before: `resolution`),
  `asked_level`, `reply_kind`, `not_repeated: true`, `stopped: true`.
- [x] T003 Mark the new scenarios `xfail(strict=True)` with the reason; each step that fixes one removes its xfail
  (strict: a fix that passes by accident fails the gate).
- [x] T004 Golden message set `backend/tests/eval/understanding/cases.yaml`: 100–150 cases (ru/es/en evenly):
  case fixture ref, pending (with id + options), history, message → expected significant `Intent` fields and
  `Action.kind`. Must include every example of spec §B4, rejections ("не тот", "другую", "ты не нашел X"), stop,
  complaints, look-alike yes/no, two-intent messages, each pending kind (QUESTIONS, CONFIRM_VARIANTS, CONFIRM_COST,
  CONFIRM_INTAKE, limit). Expected fields as in `understanding-spec.md` §4 (schemas, old→new label table, the "problem messages"
  table); every example of its §1; "все равно хочу дизель" twice (engine question open → `value`; not open → only
  `case_changes`). Sources (its §8): §1 examples, real misses from pre-prod (`turn_outcomes` / feedback with
  complaint or rephrase), the golden dialogues the prompt names; every patch in `interpreter.md` and every word of
  `phrases._YES/_NO/_CHOOSE/_GO` becomes a case before it is deleted (its §9 risk).
- [x] T005 Eval runner `backend/tests/eval/understanding/runner.py` (`-m live`): runs the current interpreter + the
  old label mapping (`understanding-spec.md` §4 "Соответствие старых меток") on the set, writes `specs/013-dialogue-quality/baseline.md` (accuracy per
  field, per language, per pending kind, list of failures) and the p95 latency of the understanding step (old
  interpreter), the reference for the +20 % criterion. Cost estimate before the run, announce it.
  Done 2026-11-27: `runner.py` + `old_path.py` (today's path per pending kind) + `scoring.py` + `oracle.py` (the
  harness ceiling: expected labels through the same path, free). Baseline on gemini-3.6-flash, €1.15: all fields
  20 % (ceiling 17 %), language 96, answer 66 (ceiling 72), goals 76 (86), reaction 82 (100), rejections 67,
  changes 80, action 28 = ceiling 28 (indicative only: no identify/assess in the harness); understanding p95
  4.6 s. Weakest: QUESTIONS pending (answer 29 %, all-ok 2 %), choose_for_me / lookalikes 0 % all-ok.
- [ ] T006 Nightly: a worker/cron task or `scripts/eval_understanding.sh` + doc in quickstart; result to
  Prometheus gauge `understanding_eval_accuracy{field}`.

Done 2026-11-26 (PR "S0a"): g13–g17 with per-turn `known_bug` (strict: a marked turn that passes fails the gate);
`schema.py` `cars:` / `reply_kind` / `not_repeated` / `stopped` / `reply_not_contains`, seeded `lineups:` /
`model_versions:` / catalogue rows (`seeding.py` wires the line-up look-up and the versions store); checks in
`quality.py`. Reproduced on the current code: C→E-Class (g13 t1), rejection + stop ignored, E-Class engine question
repeated, CX-60 settled silently (g13 t2); MX-30 BEV settled despite R-EV + URL (g14); complaint read as an answer,
question repeated, i10 "manual" settled after two asks (g15); "нет" on the card confirms (g16); "а что такое DSG?"
read as an engine answer, "давай сравним с BMW" = choose for me (g17). T004–T006 unblocked: the owner's understanding
spec is now `specs/013-dialogue-quality/understanding-spec.md` (coverage of it: `coverage-audit.md`).

## S1 — Stop the worst now (PR 2)

- [x] T010 `shared/vehicle/makes.MakeRegistry.match_model` (verify ~l.128): a model is set only by exact / alias /
  transliterated match (word-bounded); fuzzy and `sound_key` scores never select a model — they return
  "did you mean" suggestions (new function `suggest_models(text, known) -> list[str]`). Remove the +5 bonus path
  that lifts fuzzy over 100. Unit tests: "c-class" vs {E-Class, CLA, C-Class}, "Clase C" (es), "класс С"/"цешка"
  (ru translit), "Seal U" vs "Seal", "атека" → Ateca still works.
- [x] T011 `identification/stages/normalise_name.match_model`: no match → the person's model text is kept as is
  (`car.model` untouched) and the outcome carries the suggestions (UNSURE-like: CHOICES with "did you mean" + the
  person's own name first). Never replace a model the person wrote.
- [x] T012 `dialog/nodes/confirm.apply_intake` (verify ~l.390): typed text never goes through `phrases.yes_or_no` /
  `choose_for_me`; it goes to `interpret` (the S4 Understander later). Only an explicit button id confirms.
  `apply_variants`: confirm only on an explicit `yes`/`option:` id; anything else → interpret. Tests: "нет",
  "нет, другую", "да, но дизель" on the card.
- [x] T013 Buttons send ids: `application/services/interpretation/ask.intake_quick_replies` chips carry
  `{id, label}`; frontend sends `{"type":"confirm","choice":<id>}` (or a `ui_action` message) instead of the label
  text; backend maps ids. Old clients sending text stay served as text. Frontend test (vitest) for the chip payload.
- [x] T014 Line-up sanity gate (`chat/application/services/identification/lineup.py`, `acquisition/catalogue.py`
  where `brand_lineups` is written — verify): a line-up with < `lineup.min_models` (config, 5) models, or whose
  models all come from one article URL, is not stored and not used. Unit tests.
- [x] T015 Data repair (owner said yes; `scripts/deploy.sh backup` first): CLI
  `python -m automind.delivery.cli.lineups audit|purge --min-models 5` lists and deletes bad `brand_lineups` rows;
  run on pre-prod, paste the list into the PR.
- [x] T016 Remove xfail from g13 turn 1 (C-Class kept) and g16.

Done 2026-11-26 (PR "S1"): `shared/vehicle/model_names` (exact / whole words / class form / Cyrillic by sound with
letter codes agreeing; `suggest_models`), `did_you_mean` in ask_model; `intake.card_answer` (only button ids confirm);
chips carry ids (`intake.option_ids`, preset `pick`, frontend `option_id`); `intake.lineup_sanity` (maker's site, or
≥ `intake.lineup_min_models` models not all from one headline-slug article); CLI `delivery.cli.lineups`. g13 t1 and
g16 t3 green. Purge on pre-prod: after the owner's report (backup first).

## S2 — Rejection memory + verification (PR 3)

- [x] T020 Domain: `chat/domain/identification/rejection.py` — `RejectLevel` enum (MODEL, GENERATION, VERSION,
  ENGINE, GEARBOX, DRIVE), `Rejection(level, value, wanted, evidence, turn_seq)`; `CaseCar.identity_rejected:
  list[Rejection]` (Pydantic default `[]`, old cases load). Not cleared by a replace of the same car key.
- [x] T021 Interpreter (old path, until S4): the prompt + schema get `rejections` (car key, level, value, wanted,
  evidence); `validate`: evidence must be in the message; the value must be the car's current one or None.
- [x] T022 One filter `exclude_rejected(pool, rejected)` used by every strategy (SourcedVersions, CatalogueRows,
  OpenWorld, ladder options, lineup suggestions). Proposing a rejected candidate is impossible (test per strategy).
- [x] T023 `verify(candidate, car) -> Verdict(ok | contradiction(field, person_said, candidate_has))` in
  `chat/domain/identification/verify.py`: make, model (exact/alias/translit), engine/fuel/power, year/generation,
  URL page facts. Called before any proposal; a contradiction → CHOICES question naming it ("Вы писали C-Class, а я
  нашёл только E-Class — это не то. Уточните…"), never a proposal.
- [x] T024 Tactic change after a rejection: next attempt widens (make's models list from the catalogue + live
  lookup, ask for a link, or say "I could not find X; I checked: …"). Never the same question (see T052).
- [x] T025 Remove xfail g13 turn 2 (rejection heard, C-Class kept or asked, never E-Class).

Done 2026-11-27 (PR "S2"): `domain/identification/rejection` (`RejectLevel`, `Rejection`, `exclude_rejected` with a
`FactsOf` adapter per candidate kind in `application/.../identification/rejected`); `CaseCar.identity_rejected`
(default `[]`, kept by a replace; in the identity key only when non-empty, so stored outcomes of other cars hold);
`domain/case/rejections` (`CarRejection` in `CaseDelta.rejections`, recorded first in `apply`: the rejected value
leaves the car, a rejected model becomes the one wanted or unknown, the version is dropped); interpreter prompt v5
(one rule + one example) and stage `heard_rejections` (words in the message, value = the car's current one or null,
never the value wanted); the filter in SourcedVersions (versions, generation), CatalogueRows, OpenWorld (the
resolver's answer, the engines on sale, the closest names), ladder options, the line-up (catalogue_lookup, ask_model,
close_lineup); `domain/identification/verify` + stage `verify_proposal` (make, model by the person's-words rules,
generation, used year, engine; an engine the ladder already said is missing is not asked twice); `domain/
identification/tactic` + stage `change_tactic` (after a rejection a dead end or the same question widens: the make's
other models + "not found, checked …, send a link", or "no other version than the rejected one"). Not done: URL page
facts in `verify` — no page facts are stored on the car yet (S7 T070). g13 turn 2: the S2 checks are green and gate;
"stopped" (S4) and the CX-60 settle (bug 8, S5 I5) stay strict known bugs under the harness's new per-turn `later:`
blocks (a turn's message is fixed over several steps).

## S3 — Understanding in the shadow (PR 4)

- [ ] T030 `chat/domain/understanding/intent.py`: `PendingAnswer`, `Goal`/`GoalKind` (+ `stop`), `Reaction`,
  `Rejection` (reuse T020), `Understanding`, `UiAction`, `Override`, `Intent` — fields and value sets exactly as
  `understanding-spec.md` §4 (`PendingAnswer.kind` option|value|yes|no|choose_for_me; `GoalKind` compare|single|follow_up|
  change_priorities|research_more|ask_general|critique, + `stop` (spec §D1); `Reaction` thanks|complaint|correction|
  rephrase; `UiAction.kind` pick_option|confirm|decline|choose_for_me|edit_car|research_more|panel_edit (+ complain|
  quit, S6); `Intent.source` text|ui|system; `Override` rule, field, before, after, why), + `rejections` (spec §D1).
- [ ] T031 `Pending` (`chat/domain/case/casefile.py` ~l.52, verify) gets `id` and `options: list[{id, label}]`; a
  validator gives old pendings a stable content-hash id. Chips are built from `Pending.options[].id` and send
  `pending_id` with the option id (S1's `option_ids.py` scheme becomes the option id), so `stale_pending` can check a
  button; the research-limit question gets a pending id too.
- [ ] T032 `chat/application/services/understanding/`: `Understander` (port `LLM`, prompt `understander.md`
  ≤ 800 words + 15–20 examples from the set), `validate_understanding` (moved checks of `interpret.py`: car keys,
  numbers in the text, persona evidence, engine parser; new: pending_id / option_id exist), `IntentResolver` with
  rules `stale_pending`, `option_from_ui`, `no_goal_with_pending`, `cars_safety_net`, `language_hysteresis`,
  `complaint_is_not_an_answer` — each a named function with a unit test, each writes an `Override`; behaviour of each
  rule as `understanding-spec.md` §5.2. Prompt per its §6: role (2–3 sentences), four blocks (pending answer, goals, reaction,
  facts), fact rules once, 15–20 examples in three languages incl. all §1 examples; input CASE FILE / PENDING (id,
  question, options) / LAST ANSWER (new: summary of the bot's last answer, for `reaction`) / HISTORY / MESSAGE; no
  spec/FR references, no "an open question makes every message an answer", CaseDelta placement rules move into the
  schema field descriptions.
- [ ] T033 `turn_understanding` table (migration; owner's yes for a new table — additive) + port + store in
  `chat/infrastructure/`; write errors logged with chat_id/turn_id, never fail the turn. Fields as `understanding-spec.md` §7:
  input (text or UiAction + pending id), model_raw (+ prompt version, model name), rejected, overrides, intent.
  The policy part is spec 015 `policy_decisions` (T220), read by `turn_id` (no `policy_trail` field).
- [ ] T036 Prometheus: share of turns with overrides `{rule}`, share rejected, share of turns whose open question was
  asked again; p95 of the understanding step (old and new, for the +20 % criterion). Policy metrics are spec 015 T222 (not here).
- [ ] T034 Shadow: the `interpret` node runs the new chain after the old one, records both; the old decides.
  Eval runner compares new vs old on the set → `specs/013-dialogue-quality/shadow.md`.
- [ ] T035 CLI `python -m automind.delivery.cli.turn show <turn_id>` (input, model_raw, rejected, overrides, intent,
  and the policy passes through spec 015's `why` renderer, T223).

## S4 — Switch to Intent (PR 5; deploy checkpoint)

- [ ] T040 Node `understand` (alias `interpret` kept) writes `intent`; `apply_delta` → `apply_changes` (alias kept):
  only applies `case_changes` + the pending answer, never rewrites intent. `intent` reset per turn (with 014 C3 the
  reset is `begin_turn`'s, `PER_TURN_RESET` deleted — one release, no double mechanism); language from the previous
  turn, never "en". While a turn waits on `wait_*`, a typed answer goes to `understand` and, with `answer_to_pending`
  for that confirmation, the router leads to its `apply_*` with the ready answer (014 T130 adds this target to
  `UnderstandOut.next()`). The pending closes only when answered or when the topic changes (rule: owner's decision
  G5). `report_saved` → `Intent(source="system")`, never a person's intent.
- [ ] T041 Policy reads `Intent` **on spec 015's `Rule`/`Situation`/`Decision`** (015 PL1–PL3 done first):
  `Situation.intent` replaces `request` (one, not both); new rules are `Rule` classes with `RuleOutcome` reasons;
  `AnswerOrReport` split into goal rules here (015 D3); `ANSWER_AND_REASK` added to `ActionKind` and `ROUTES` (015
  T203 completeness test). Behaviour: goals without preconditions answered first;
  `ANSWER_AND_REASK` when a bot question is open; goal `stop` → end the open question/search, say so, case kept;
  reason names the goal and the rule; the bot's question names its reason ("Чтобы сравнить, нужен год Prado"); several
  goals: those without preconditions first, then the first one with preconditions (staging per G6). The trail is `Decision.trail`
  in `policy_decisions` (015 T220), not a `turn_understanding` field.
  Also fixes the live miss of 2026-11-27 (chat eb81dd90 t2): a complaint/correction with an unchanged case and no
  report yet answered "nothing changed since the last report" — remove the strict xfail
  `tests/unit/chat/dialog/policy/test_policy_known_bugs.py`.
- [ ] T042 `apply_*` confirmation nodes and `research.apply_limit` take a ready `PendingAnswer` / `UiAction`; text
  always via `understand`. Word lists in `phrases.py` (`_YES/_NO/_CHOOSE/_GO`, `yes_or_no`, `choose_for_me`,
  `go_ahead`) only in the degraded mode (model down) and only on an exact whole-phrase match; no match → the soft
  "сервис перегружен" ending. Removed: the text stage `picked_option` (`interpretation/service.py`,
  `stages/picked_option.py`), the `choose_for_me` rewrite in `InterpretationService.apply`, `research.apply_limit`'s
  `yes_or_no`, the duplicate `_card_edit` in `nodes/confirm.py`.
- [ ] T043 Readers of `request_kind` (policy rules via `Situation.intent` — T041 on spec 015, understand.py, research.py,
  report_writer, report_followup, tracing, metrics) moved to `Intent`; `tracing.previous_signals` from
  `intent.reaction` of the turn. `turns.request_kind` column keeps a derived value for the admin until removed.
  `Interpretation.relation` removed (replaced by `reaction`).
- [ ] T044 Acceptance numbers of spec §E on the eval set; no regression vs baseline where old was right.
- [ ] T045 Remove xfail g17; all §B4 examples green.
- [ ] T046 Buttons as `UiAction` (understanding spec §3): car edit → `edit_car` with precise errors (no "which car?"
  for every failure), preset → `research_more` / `panel_edit` (rescore), `source="ui"`, the model never called.

## S5 — Identification subgraph (PR 6a spike, PR 6b)

- [ ] T050 Spike (throwaway branch, report in `research.md`): LangGraph subgraph with `interrupt` inside, on our
  Postgres checkpointer, resumed through the parent thread; node-id stability; what `check_checkpoints.py` sees.
- [ ] T051 `chat/domain/identification/state.py`: `IdentityState` enum (NAMED, MATCHED, NARROWING, PROPOSED,
  CONFIRMED, UNSURE, NOT_FOUND, REJECTED, ABANDONED), `TRANSITIONS` table, `check_move`; `CaseCar.identity_state`
  (old cases derive it from `resolution` + `identify.outcome` on read).
- [ ] T052 Invariants I1–I7 as guards in one module (`chat/domain/identification/invariants.py`), each with a unit
  test; a blocked transition is logged into `identification_trail` and counted
  (`identification_invariant_blocked_total{rule}`). I4 repeat guard: (car, level, options hash) asked before → change
  tactic (T024).
- [ ] T053 Subgraph `identify_dialog` (`chat/dialog/identification/graph.py`): consumes `Intent` (answer, rejections,
  case_changes of the car, stop), runs the strategies as candidate sources, asks, proposes; exits to `assess` only
  when every car is CONFIRMED or ABANDONED. The main graph's `identify` node becomes the subgraph entry (alias kept);
  identity questions leave `intake`/`variants` confirmations (the card confirms cost/person only).
- [ ] T054 `identification_trail` (per car: states, candidates with scores and sources, blocked invariants) in the
  `turn_understanding` record.
- [ ] T055 `tests/graph/graph_shape.json` updated; checkpoint compatibility proved by `check_checkpoints.py` on prod
  blobs; g13–g15 fully green.
- [ ] T056 I8 (finding A, chat d170b861 t5–t7): ask counters keyed by the car's identity (make, model, generation);
  reset on a model change; the limit auto-pick and the "asked twice" note only for questions this identity was
  asked. Unit test: car#1 Mercedes C-Class after two E-Class engine asks → the C-Class engine question is asked,
  not auto-picked; a dialogue case in the golden set (g13 extension) for the same.
- [ ] T057 I9 (finding B, chat d170b861 t9): relative generation words ("newer/older/такой же но новее/previous")
  become a relation (`GenerationRelation`), resolved against the model's generations or asked ("already the
  newest"); never `generation_hint` text. `vehicle_variants` gets only versions a source names (guard in the
  variant store + unit test: a `LOOKED_UP` row whose key carries a relation word or an unsourced engine is
  refused). Golden case: "такой же но более нового поколения" on a W206 → the "already the newest" answer.
  Data repair (owner's yes 2026-11-27, backup first): remove `f28fe7f7…` with its dependents (evidence, claims,
  spec_values, research_jobs/runs, page_relevance, review_items, …) in one transaction; chat d170b861 still opens.

## S6 — Complain / quit at every question (PR 7)

- [ ] T060 Every question block (identification, card, choices, limit) gets buttons "Пожаловаться" (+ short reason)
  and "Закончить" → `UiAction(complain|quit)`; frontend + vitest.
- [ ] T061 A complaint opens a self-diagnosis issue at once (trail + open question); quit during a question → turn
  outcome "abandoned at <identity_state|pending kind>", counted as a failure of that step.
- [ ] T062 Signals: "identification changed the person's model", "person rejected the identified car", "user URL not
  read", "question repeated"; `config/insight.yaml files:` paths fixed + a gate check in `check.sh` that each exists.

## S7 — The rest of §0a (PR 8, may split)

- [ ] T070 The person's URL read first; the version must match the page (I6).
- [ ] T071 EREV a powertrain of its own (`shared/vehicle/engine.Fuel`, interpreter/understander, identification,
  energy); Mazda R-EV its family; known EREVs stored as PHEV migrated (owner's yes, backup).
- [ ] T072 LLM hints rank, never filter (`versions.lookup(fuel=…)`); a contradiction asks.
- [ ] T073 A named version rebuilds the pool; EV/EREV never offered a manual gearbox.
- [ ] T074 Answers routed to the right car (pending option ids make this structural); reply language kept.
- [ ] T075 g14 fully green; live replay of 4bb83866 and d170b861 on pre-prod shown to the owner.

## After S7

Update `docs/next-session.md`; spec 012 resumes at A4c.
