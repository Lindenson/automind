# Spec 013 — Dialogue quality: understanding the person and identifying the car

**Branch**: `013-dialogue-quality` · **Created**: 2026-11-26 · **Status**: Approved by the owner 2026-11-26 (§G)

**Input**: (1) the owner's chats `d170b861` (Clase C → E-Class, 2026-11-26) and `4bb83866` (MX-30 R-EV + URL,
2026-11-08), `docs/next-session.md` §00 and §0a; (2) the understanding spec of 2026-11-26 ("Переделка слоя понимания
намерений"), merged here in full (§B, §D1, §E). Its non-goal "identification is not touched" is lifted by the owner:
identification is the other half of the same failure.

**Priority**: before everything else, spec 012 included (A4c and later wait). New code follows the 012 code-shape
contract (`specs/012-refactoring/contracts/code-shape.md`: ports, named stages, states not words, ≤ 200 lines/module).

---

## A. The problem in one sentence

The system does not hear "no / wrong / pick another". It guesses the car with full confidence, does not check the
guess against what the person wrote, has no memory of what the person rejected, and has no notion of "the person is
not satisfied yet". The person is put through the same wrong choice again and again.

## B. Evidence (verified 2026-11-26 in code and in the pre-prod database)

### B1. Chat d170b861 — what happened, step by step

| Turn | Person | What the model understood | What code made of it |
|---|---|---|---|
| 1 | "я выбираю между Clase C Berlina мерседесом и Маздой CX-60" | `Mercedes-Benz / C-Class`, body Berlina (case event 3) — **correct** | identification replaced it with `E-Class W214` (event 6), proposed "E 200 automatic" (event 7); Mazda settled to "3.3 200 CV RWD Exclusive-Line" without a question |
| 2 | "ты не нашел мерседес класс C. отменяй поиск. пошел в жопу" | `correction`, car replaced by `C-Class` again (event 14) — **correct** | the same identification path ran from scratch → `E-Class` again (event 17); "stop" ignored; the E-Class engine question repeated |

The reply's first sentence (written by a model) says "седан Mercedes C-класса"; the card under it (written by code)
says "Mercedes-Benz E-Class". **The model heard the person. The code overrode it.**

### B2. Why it picked another model

- `shared/vehicle/makes.MakeRegistry.match_model` (called from `identification/stages/normalise_name.match_model`):
  the score is `max(WRatio, ratio(sound_key))`; `sound_key("c-class") == sound_key("e-class")` → 100, plus a +5
  same-word-count bonus → 105. The margin check runs only for scores `< 100` (meant for exact names), so a phonetic
  guess passes as if written exactly.
- The known set had no C-Class: the stored Mercedes-Benz ES line-up (`brand_lineups`, 2026-11-26 19:08) has one
  model, "Clase S", taken from a news article about S-Class prices. Nothing checks a line-up for sanity.

### B3. Why it is deaf to "no"

- **No memory of a rejection.** `CaseCar` has no field for "the person said: not this". A correction replaces the
  car's facts; the identification runs the same deterministic path on the same facts and returns the same answer.
- **No verification.** After identification nothing compares the result with the person's words (model "C" in,
  model "E" out, nobody notices).
- **Words before the model.** On the intake card `nodes/confirm.apply_intake` checks ≤ 3 words without digits against
  `phrases._YES/_NO/_CHOOSE`: a typed **"нет" becomes `stop`, which marks every proposed car CONFIRMED and declines
  the research**: "no" confirms the wrong car. `apply_variants` confirms the proposal for any unrecognised choice.
- **Buttons send words.** Quick replies send their label as text ("Нет, другую", "E 200"); code then guesses the
  meaning from the words.
- **A correction has no consequence.** `request_kind=correction` is a label; no policy rule says "the person
  rejected the identification: change tactic". There is no stop / quit intent (bug 10); a complaint during a question
  is parsed as an answer (bug 6); the same question is asked again (bug 7); single survivors settle silently (bug 8).
- **No dialogue for identification.** One pass per turn: `interpret → apply_delta → identify → assess → policy`.
  Identification is a function call, not a conversation with states (proposed / rejected / confirmed by the person).

### B4. Understanding layer (from the understanding spec)

The intent is decided in 8 places; a single `request` label of 14 values is rewritten by keyword lists
(`phrases._YES/_NO/_CHOOSE/_GO`) before and after the model; one label per message although messages carry two
intents; an open bot question swallows the person's own question; the interpreter prompt is 166 lines of patches; no
regression set. Examples (all verified in code): "да, но дизель" → yes, diesel lost; "давно хотел дизель" → yes;
"дайте подумать" → yes; "para mi familia" → no; "answer me about fuel" → no; "все равно хочу дизель" → choose for me;
"do you have any…" → choose for me; "давай сравним с BMW" during a version question → choose for me; "а что такое
DSG?" during the gearbox question → taken as the answer; "да, и добавь Hyundai" → one intent lost; "переформулируйте"
in a Russian chat → English reply.

## C. Goals

1. **Never confidently wrong.** A model name the person wrote is kept unless an exact (or transliterated) match says
   otherwise; any change of the person's words is asked, never done silently.
2. **"No" is heard.** A rejection ("not this", "wrong", "another one", "you did not find X") is a structured fact on
   the car; a rejected candidate is never proposed again; the next proposal changes tactic.
3. **Identification is a dialogue that ends at the person's satisfaction**: every car leaves it only CONFIRMED by the
   person (or "choose for me", or the person stops). No circles: a repeated question is a dead end that changes tactic.
4. **One place understands text, one model call; buttons send ids, not words** (understanding spec goals 1–7).
5. **Stop, complain, rephrase work at any step**; each is a signal for self-diagnosis.
6. **Every turn is explainable from one record**: what the model said, what code changed and why, which rule chose
   the action, and per car which identification states were traversed.
7. **Measured before and after** on a golden set of messages and on scripted dialogues from the owner's chats.

Non-goals: the model does not choose the action (code does); `CaseDelta` and domain `apply()` stay; research, report
and guard are untouched; code checks of model output (numbers in the text, car keys exist) stay.

## D. Design

### D1. Understanding (the understanding spec, kept as written, with three additions)

Schemas `PendingAnswer`, `Goal`, `Reaction`, `Understanding`, `UiAction`, `Override`, `Intent`; components
`Understander` (one structured call) → `validate_understanding` → `IntentResolver` (the only place that may correct
the understanding; each correction is an `Override`) → `apply_changes` → `policy` (reads `Intent`, never text).
Resolver rules: `stale_pending`, `option_from_ui`, `no_goal_with_pending`, `cars_safety_net`, `language_hysteresis`.
Word lists survive only in the degraded mode (model down) and only on an exact whole-phrase match. Pending gets an
`id` and `options[].id`; buttons send them. Policy starts from the goal (`ANSWER_AND_REASK` for a question asked
while a bot question is open). New prompt `understander.md` ≤ ~800 words with 15–20 examples from the golden set.
Mapping of old labels as in the understanding spec §4.

Additions:
- **`rejections: list[Rejection]`** in `Understanding`/`Intent`: `{car_key, level: MODEL|GENERATION|VERSION|ENGINE|…,
  value: str | None (what is rejected; None = "the current one"), wanted: str | None ("класс C"), evidence}`.
  "ты не нашел мерседес класс C" → `Rejection(car#1, MODEL, value="E-Class", wanted="C-Class")`.
- **`GoalKind` gains `stop`** (end the current search/question; the case stays): "отменяй поиск", "хватит", "stop".
- **`Reaction` "complaint" never answers a pending question**: the resolver drops `answer_to_pending` when the
  reaction is a complaint without an explicit answer in the evidence.

### D2. Identification as a dialogue: a subgraph with a state machine per car

The subgraph `identify_dialog` owns everything about "which car exactly": matching, proposals, questions about
model / generation / engine / gearbox / drive, the person's answers and rejections. The main graph enters it while
any car is not `CONFIRMED`, and leaves it to `assess` only when every car is `CONFIRMED` or `ABANDONED`. Inside, the
person's text still goes through D1 (one understanding place); the subgraph consumes `Intent.answer_to_pending`,
`Intent.rejections`, `case_changes` of the car, and `stop`.

Per-car state (an enum with a transition table, rule "States, not words"):

```
NAMED ──match──▶ MATCHED ──pool──▶ NARROWING ──one left──▶ PROPOSED ──yes──▶ CONFIRMED
  │  no exact     │ model unknown      │ open level              │ no / rejection
  ▼              ▼                    ▼ (ask with options)       ▼
UNSURE ◀──────── NOT_FOUND           NARROWING ◀── answer     REJECTED ──exclude, change tactic──▶ MATCHED|UNSURE
(ask: "did you mean X or Y?"; the person's word wins)                         any state ──stop──▶ ABANDONED
```

Invariants (each a unit test and a runtime check that blocks the transition and logs it):
- **I1 the person's words win**: the model leaves `NAMED` only by an exact/alias/transliterated match of the
  person's words; a fuzzy/phonetic match never sets the model, it only produces "did you mean" options (`UNSURE`).
- **I2 verification**: before `PROPOSED`, `verify(candidate, car)` checks make, model, and every fact the person gave
  (engine, fuel, year, URL page); a mismatch → `UNSURE` with the contradiction named, never a silent proposal.
- **I3 a rejection is remembered**: `car.identity.rejected` keeps rejected models/versions/engines; candidate pools
  exclude them; proposing a rejected candidate is impossible (filtered in one place).
- **I4 no circles**: the same question (car, level, options) is never asked twice; on a repeat the tactic changes —
  open list of the make's models, ask for a link, or say plainly "I cannot find X; here is what I checked".
- **I5 nothing settles silently**: `CONFIRMED` only from the person's yes / pick / "choose for me"; a single
  survivor becomes `PROPOSED` (shown on the card), never `CONFIRMED`.
- **I6 the person's evidence first**: a page the person sent is read first and the version must match it; LLM hints
  rank candidates, they never filter them; a contradiction asks.
- **I7 every proposal carries its evidence** (source, which words of the person matched) — shown on the card.
- **I8 attempts belong to the identity being asked about** (owner's chat d170b861, finding A): ask counters, the
  "asked twice" limit and the auto-pick it triggers are keyed by the car's identity (make, model, generation), not
  by the car slot; when the model changes (replace, correction, rejection) they start from zero, and no "asked
  twice" note is shown for a question this identity was never asked (`ladder/steps.py` `decide(asks=…)`).
- **I9 a relative generation is not a name** (finding B): "newer", "older", "такой же но новее", "the previous one"
  are relations to a known generation — resolved against the model's generation list (or asked: "W206 is already
  the newest; did you mean …?"), never stored as `generation_hint` text nor used to build a version. Nothing
  enters `vehicle_variants` unless a source names that version (no `LOOKED_UP` row assembled from the person's
  words plus a guess); an unverified candidate lives only in the identification trail.

Strategies (sourced versions, catalogue rows, open world) remain, behind the `Fallback` protocol, but they return
candidates to the state machine instead of a final outcome. The line-up is used only with a sanity gate (D4).

Checkpoints: node ids are stored state. The old `identify` node and the `wait_*` ids stay as aliases until a release
after which no thread waits on them (`scripts/check_checkpoints.py` proves it on prod blobs). LangGraph subgraph
interrupts resume through the parent thread (verify in the S5 spike before committing to the shape).

### D3. Stop, complain, quit at any step (bug 10)

Every question block (identification, intake card, choices, limits) carries two buttons: "Пожаловаться" (opens a
short reason) and "Закончить". `UiAction(kind="complain"|"quit")`; typed text reaches the same through D1
(`reaction=complaint`, goal `stop`). A complaint opens a self-diagnosis issue at once with the turn's trail and the
open question; quitting during a question is recorded as "abandoned at <state>" — a failure of that step.

### D4. Data sanity

- A make's line-up from fewer than N models (config) or from a single news article is not stored; the existing
  garbage rows are listed and removed (owner's yes, backup first).
- Self-diagnosis signals: "identification changed the person's model", "person rejected the identified car", "user
  URL not read", "question repeated"; `config/insight.yaml files:` paths fixed + a gate check that they exist.

### D5. Observability

One record per turn, `turn_understanding` (understanding spec §7: input, model_raw, rejected, overrides, intent;
the policy passes are spec 015's `policy_decisions`, joined by `turn_id`) plus `identification_trail` per car: states traversed, candidates with scores and sources, invariant
that blocked a transition. Written through a port; a write error never fails the turn. Prometheus: share of turns
with overrides (by rule), rejected, repeated questions, identification changed the person's words. A CLI
`python -m automind.delivery.cli.turn show <turn_id>` prints the whole chain.

## E. Testing and acceptance

Three levels (understanding spec §8) plus dialogues:
- **Unit**: validate_understanding, each resolver rule, each state transition and invariant, policy on a given Intent.
- **Golden set (eval)**: 100–150 messages in YAML (ru/es/en evenly; every pending kind; two-intent messages; look-alike
  yes/no; all §B4 examples; rejections and stop) → expected Intent fields and Action.kind; real model; run on every
  prompt/schema/rule change and nightly; first run on the old code = the baseline.
- **Dialogue regression**: scripted multi-turn scenarios through the whole graph with recorded search hits/pages and a
  scripted model: d170b861 (C-Class + CX-60 + "отменяй"), 4bb83866 (MX-30 R-EV + URL + complaint), i10 "manual",
  CX-60 auto-settle, "нет" on the card, "давай сравним с BMW" during a question. Each asserts the car identified, the
  state of each car, and the reply kind per turn. Part of `check.sh`.

Acceptance:
- [ ] All §B1/§B4 cases and the dialogue scenarios pass; each failed on the old code (proved by the baseline run).
- [ ] No transition violates I1–I7 on the golden set and dialogues (the runtime check counts 0).
- [ ] `answer_to_pending` accuracy ≥ 97%, goals ≥ 92%, `Action.kind` ≥ 95% (thresholds revisited after the baseline).
- [ ] No regression against the old code where the old code was right.
- [ ] Understanding step p95 latency at most +20%.
- [ ] Every turn leaves `turn_understanding` (+ `identification_trail` when identification ran).
- [ ] The owner's chats replayed live on pre-prod give the right car and hear "no" and "stop".

## F. Steps (one PR each, merged to main, pre-prod redeployed, owner's chat replayed live after each)

| # | Step | Gives the owner |
|---|---|---|
| S0 | **Measuring first**: golden set (YAML) + eval runner; dialogue regression harness with recorded pages; run on the current code → baseline numbers | the failures as red tests |
| S1 | **Stop the worst now** (small, on the old structure): no phonetic/fuzzy model jump (I1) + the bonus/margin bug; "нет" on the card never confirms; `apply_variants` confirms only on an explicit yes; buttons send option ids; line-up sanity gate + remove the garbage line-ups | C-Class stays C-Class; "нет" stops confirming |
| S2 | **Rejection memory + verification**: `car.identity.rejected`, `verify()` before a proposal, `UNSURE` asks with the contradiction; correction with a rejection changes tactic | "ты не нашел класс C" is heard |
| S3 | **Understanding in the shadow**: `Understander` + schema + `validate_understanding` + `IntentResolver` + `turn_understanding` record; runs beside the old interpreter, the golden set compares both | numbers: new vs old |
| S4 | **Switch to Intent**: policy reads `Intent`; `apply_*` nodes stop parsing text; `ANSWER_AND_REASK`; `stop` goal; complaint never an answer; word lists only in degraded mode; old labels removed | two intents in one message; questions not lost |
| S5 | **Identification subgraph**: spike (interrupts inside a subgraph on our checkpointer), then the per-car state machine with I1–I7, repeat guard, exit only at CONFIRMED/ABANDONED; checkpoint aliases | no circles; dialogue ends at the person's satisfaction |
| S6 | **Complain / quit buttons at every question** + self-diagnosis signals (D3, D4) | every failure becomes an issue |
| S7 | **The rest of §0a**: URL first, EREV as a powertrain, hints rank not filter, a named version rebuilds the pool, answers routed to the right car and language | MX-30 R-EV chat right |

Then spec 012 resumes at A4c. Checkpoint compatibility (understanding spec §9): new state keys are added, old keys
(`interpretation`, `request_kind`) are read until S4 and removed after; Pending without an id gets a stable content
hash id on read; old clients sending button words are served as text with the option list.

## G. Owner's decisions (2026-11-26)

1. Order: S0 → S1 → S2 → … → S7, as in §F. "Делаем всё."
2. Live eval of the golden set on the real model (≈ €1–2 per run): yes, on every prompt/schema/rule change and nightly.
3. Line-ups with fewer than 5 models (or from a single news article) are removed, backup first; N = 5 in config.
4. (2026-11-27) Findings A and B from the review of d170b861 join S5 as invariants I8 and I9 (T056, T057); the
   invented row `vehicle_variants` `f28fe7f7…` ("C 200 DSG FWD", key `…|newer|c 200 dsg|mhev`) stays until T057:
   ≈ 320 dependent rows in 12 tables (no cascade) and 4 case_files versions + 1 message of d170b861 point to it, so
   T057 removes it with its dependents and proves the chat still opens (backup `automind-20261127-101515.sql.gz`).

Execution: `tasks.md` (one phase = one PR).

### Decisions G4–G11 (from the understanding spec §10 and the coverage audit) — approved by the owner 2026-11-27 as proposed ("согласен с тобой")

- G4 (§10 Q1): the model of the `understander` role and the budget per turn (latency, cost). Decision: the cheap fast
  model of today's `asker` role; ≤ +20 % p95 (acceptance), buttons never call it.
- G5 (§10 Q5): when a topic change closes the open question unanswered. Decision: a `compare`/`single` goal naming
  other cars than the pending's, or the person's `stop`.
- G6 (§9 risk): several goals — first goal only at S4, the rest recorded in the turn record; full support in S4b
  after the eval shows no loss (the source's staging).
- G7 (§10 Q2): who collects real misses into the eval set. Decision: a weekly script over `turn_outcomes`/feedback
  (complaint, rephrase) proposes cases; the owner confirms the expected intent.
- G8 (§10 Q6): a per-chat old/new switch at S4. Decision: no switch; the shadow (S3) and the eval are the gate, a
  config flag reverts globally.
- G9 (§10 Q4): ANSWER_AND_REASK always.
- G10 (§10 Q7): accuracy thresholds of §E confirmed after the baseline run (T005).
- G11 (source §11.6 vs spec 014): the source puts 014's steps 3–4 "with stage 3 of the rework"; 014 (approved) puts
  C3 with S4 and C4 with S5. Keep 014's order: sections are born with `Intent` at S4; `goto` with the subgraph at S5.
