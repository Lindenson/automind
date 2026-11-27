# Golden message set — understanding layer (spec 013 T004)

148 single messages, each in a named context, with the `Intent` fields that matter and the expected `Action.kind`.
The set was written before any new understanding code (understanding-spec §8). T005 runs it on the current
interpreter to get the baseline. After that, every change to the prompt, the schema or the resolver rules is run
against it.

| File | What |
|---|---|
| `cases.yaml` | the cases: `id`, `lang`, `sources` (+ `ref`), `fixture`, `pending`, `history`, `message`, `tags`, `words`, `patches`, `note`, `expect` |
| `fixtures.yaml` | named case files (`cases:`) and open questions (`pendings:`): pending id, kind, question, items with car, topic and options with ids |
| `vocab.py` / `fixture_models.py` / `schema.py` | the format (Pydantic, `extra="forbid"`: a misspelt key is an error, never silently "not checked") |
| `coverage.py` | what the set must cover (frozen §1 messages, interpreter.md v5 rules, phrases word lists, minimum per category) and `check_set` |
| `test_cases.py` | fast unit test, no DB and no model: `uv run pytest -q tests/eval/understanding` |

## What `expect` means

- `language`: always checked.
- `answer`: always checked. If it is absent, the message does not answer the open question. If present, the
  `pending_id` must match, and `kind` is one of `option | value | yes | no | choose_for_me`. `option_id` is checked
  when given and must be one of the pending's options.
- `goals`: always checked, as an ordered list of kinds. Absent means no goal. `focus_cars` / `focus_areas` are checked
  only when given. `stop` is spec 013 §D1's extra kind.
- `reaction`: `thanks | complaint | correction | rephrase`. `none` means there must be no reaction. If absent, it is
  not checked.
- `rejections`: checked only when given; `[]` means there must be none.
- `changes`: checked only when given. It lists the key `case_changes` only. `empty: true` means nothing changes;
  `add_cars: []` means no car is added (cars already in the case keep their keys).
- `action`: always checked. It is a `domain.decision.ActionKind`, or `ANSWER_AND_REASK` (013 T041).

Option ids follow S1's scheme (`domain/intake/option_ids.py`) and today's confirmation ids (see the header of
`fixtures.yaml`). Fixtures carry no catalogue, so a car that is not CONFIRMED / AUTO_OK still needs identification.

## Counts

Per language: **ru 55 · es 46 · en 47**.

Per source (a case can have several): phrases 61, interpreter.md 42, t004 (written to fill a T004 coverage line) 30,
golden 16, spec§1 12, preprod-miss 7, preprod 6, problem-table 6.

Per category (`coverage.categories`: tags plus the derived pending kind / source / words / patches), as ru / es / en:

| Category | Cases | ru | es | en | Minimum |
|---|---|---|---|---|---|
| spec1 (every §1 / §B4 example) | 11 | 8 | 1 | 2 | 11 |
| problem_table | 6 | 6 | 0 | 0 | 5 |
| diesel_engine_open / _closed ("все равно хочу дизель") | 1 / 1 | 1 / 1 | – | – | 1 / 1 |
| rejection ("не тот", "нет, другую", "ты не нашел X", …) | 12 | 6 | 3 | 3 | 6 |
| stop ("отменяй поиск", …) | 7 | 4 | 2 | 1 | 4 |
| complaint | 10 | 5 | 3 | 2 | 6 |
| lookalike_yes / lookalike_no / lookalike_choose | 8 / 6 / 4 | 3 / 1 / 3 | 3 / 2 / 0 | 2 / 3 / 1 | 6 / 5 / 3 |
| two_intents | 12 | 7 | 3 | 2 | 6 |
| question_during_question | 12 | 4 | 4 | 4 | 6 |
| plain_yes / plain_no / choose_for_me | 20 / 10 / 12 | 5 / 4 / 6 | 8 / 2 / 3 | 7 / 4 / 3 | 6 / 5 / 8 |
| button_text (an old client sends the chip label) | 7 | 2 | 4 | 1 | 5 |
| language_hysteresis | 6 | 6 | 0 | 0 | 3 |
| pending QUESTIONS | 51 | 28 | 12 | 11 | 15 |
| pending CONFIRM_VARIANTS | 10 | 2 | 4 | 4 | 5 |
| pending CONFIRM_COST | 11 | 3 | 3 | 5 | 5 |
| pending CONFIRM_INTAKE | 23 | 9 | 9 | 5 | 5 |
| pending LIMIT (research limit) | 13 | 3 | 6 | 4 | 5 |
| no_pending | 40 | 10 | 12 | 18 | 15 |
| golden | 16 | 8 | 0 | 8 | 8 |
| interpreter_patch (every rule and example of v5) | 46 | 14 | 16 | 16 | 18 |
| phrases_word (every word of `_YES/_NO/_CHOOSE/_GO`) | 68 | 25 | 21 | 22 | 30 |
| preprod_miss | 7 | 7 | 0 | 0 | 6 |

The unit test also requires every pending kind in every language. It fails when `phrases`' word lists or the
interpreter prompt version change, so the set gets new cases before the old path loses them (understanding-spec §9).

## Sources and honesty

- **preprod-miss**: read-only from pre-prod `chat_messages` / `turn_outcomes` / `feedback` on 2026-11-27. These are
  the chats with feedback `complaint` / `correction` or the failure class `not_understood`: d170b861, eb81dd90 and
  4bb83866. Messages are copied as typed; they contained no personal data. All real misses are Russian. Pre-prod
  has no Spanish or English misses yet, so the es / en complaints, rejections and stops are `t004` (written,
  marked as such). `preprod` = a real message that was not a miss.
- **golden**: g1–g4, g7, g8 (the dialogues the prompt's few-shots come from) and g13–g17.
- **t004**: written by hand to cover a T004 line that no real source covers.

## Provisional expectations (to revisit in T005 / T041)

- Goal `stop`: spec 015 has no `ActionKind` for it yet. Its cases expect `ANSWER_FROM_CONTEXT`, the kind that ends the
  turn with a message from the case. T041 decides the real kind; then update the 7 stop cases.
- After the last answer of a QUESTIONS pending: `CONFIRM_INTAKE` (the card, as in g16). Card yes → `RESEARCH`;
  card "not now" / cost skip / limit stop → `REPORT`; a typed "no" or a rejection → `ASK`.
- A typed priority change after a report → `ANSWER_FROM_CONTEXT` (as g1 / g3 / g4 expect today). Other new facts
  after a report → `REPORT`.

## How T005 uses it

For each case, the runner builds the `CaseFile` from the fixture and the `Pending` (id + options) from the pending.
It runs the current interpreter (real model, `-m live`). It maps the old `Interpretation` to the new fields with
understanding-spec §4 "Соответствие старых меток", runs the policy to get `Action.kind`, and compares with `expect`.
It reports accuracy per field (`answer` present+kind, `goals`, `action`, plus `reaction` / `changes` / `rejections`
where given), per language, per pending kind and per category, and lists the failures. All of this goes into
`specs/013-dialogue-quality/baseline.md`, along with the p95 latency of the understanding step.
