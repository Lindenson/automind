# Tasks — Spec 016 Narration

One step = one PR, merged to main; pre-prod redeployed after each and the owner's chat replayed live (a report and a
follow-up question); gate: `scripts/check.sh` green, structure ratchet does not grow (N5: −12 lines), behaviour diff
listed in the PR, `check_checkpoints.py` 0 module paths, pr-self-check answered. Paths under
`backend/src/automind/chat/` unless stated. "(verify)" = read 2026-11-27. Placement (spec §H D10): N1 now, beside 015
PL2; N2–N5 after 013 S7, beside 012 A4c+.

## N1 — Quick fixes on the old guard (PR 1, now; independent of N2–N5)

- [x] T301 `dialog/guard.py`: `ALWAYS_OK` deleted; before the number check, metric-name phrases are cut from the
  sentence by one closed table in the module's contracts section ("0–100 км/ч", "0-100 km/h", "0–200", "400 m",
  "0-62 mph", "l/100 km", "л/100 км", "kWh/100 km"); `_NUM_RE` gets `_CHECKED_RE`'s model-code look-behind, so a label
  "2.8 D-4D" puts no 4 in the bag (`guard.py:15,17`, verify).
- [x] T302 Tolerance "equal at the written precision": a written number matches a fact when the fact rounded to the
  written number's step (its decimals, or its trailing zeros for integers) equals it — 205 ≠ 204, "9,8" matches 9.75,
  "42 500" matches 42 480, "3 600" matches 3 600 (`guard.py:58-62`, verify).
- [x] T303 One sentence splitter for `check_numbers`, `report_violations`, `drop_sentences` (`guard.py:84,157,252`,
  verify) that does not split after the abbreviations of one table ("л.с.", "т.д.", "т.е.", "т.к.", "г.", "e.g.",
  "approx.", "aprox.") or a decimal point; test: "Prado — 204 л.с. и 9,9 л на 100 км" is one sentence.
- [x] T304 Topic map: every key of `backend/config/insights.yaml` (verify) maps to a `TOPIC_WORDS` topic
  (`reliability_score` → `reliability`, `measured_0_100` → `accel_0_100`, `max_torque`, `top_speed`, `rear_legroom`,
  `euro_ncap_stars` get their words); a test asserts every insight key is mapped. `tie_winner` matches the car by
  `_aliases` (as `_subject` does), not by the full name (`guard.py:242`, verify).
- [x] T305 `dialog/report_writer.py`: `report_check` typed (`comp: Computed`, no `Any`); `except Exception` →
  `except ProviderUnavailable` and errors whose `classify` is in `TRANSIENT` (`shared/contracts/provider_failure.py`);
  any other exception propagates (turn FAILED via `dialog/turn/endings.py`); a test drives each path.
- [x] T306 `write_answer` runs the same `report_check` (all four rules, one rewrite with the `answerer` role) instead
  of `saving_costlier` only (`report_writer.py:62-65`, verify).
- [x] T307 (only if spec §H D3 = yes) a quiet removal notice in three languages (`dialog/phrases.py`), appended once
  when the guard removed a sentence; `log_removed` unchanged.
- [x] T308 Tests: `backend/tests/unit/chat/dialog/test_guard_reproduction.py` — the §1 table and the extra probes of
  `coverage-audit.md` §B as a parametrized table with the expected new result; the old results pasted in the PR
  (run on main first). Existing tests updated where a fixed behaviour changes them:
  `backend/tests/unit/chat/dialog/test_guard.py`, `test_report_check.py`, `test_review_regressions.py`,
  `backend/tests/unit/chat/domain/cost/test_report_tco.py`, `backend/tests/integration/test_analysis_db.py` (verify).
- [x] T309 Behaviour diff in the PR: sentences now removed that passed (205 hp, made-up percentages), sentences now
  kept that were cut (abbreviation fragments), answers now rewritten.

N1 done (PR `016-n1-guard-fixes`). Findings: (1) T302 as written ("trailing zeros for integers") let "10" stand
for 6.7 and broke FR-033: trailing zeros are a precision only from 1000 up ("42 500" ≈ 42 480); below 1000 an
integer is exact. (2) "4 %" passed not only through "D-4D": the facts' "€3.550" was also read as 3.55. A single
3-digit group next to a euro sign now has only its thousands reading. (3) A generation code in the facts still gives
its number ("J150" → 150), so "Prado 150" in the text stays (golden g1 lost its headline otherwise); only a hyphenated
engine code ("D-4D") gives none. (4) A line whose sentences all go takes its list mark along (no "2." left).
(5) The old `except Exception` hid exhausted test scripts: golden g2 turn 3 always dropped its headline silently; the
cassettes of g2, g4, g5, g6 now carry the rewrite. (6) Torque, top speed, rear legroom, Euro NCAP, measured 0–100 and
the reliability score have topic words; "more power and torque" with torque a tie is now rewritten (17 graph/golden
dumps). Structure 1381 → 1379 (`regex` in `check_numbers`, `drop_sentences`).

## N2 — FactSheet, renderer, record (PR 2; behaviour: number formatting only)

- [ ] T310 `application/services/narration/contracts.py` (spec §D1): `Unit`, `Metric` (insights keys + TCO item kinds
  + `tco_period`, `tco_per_year`), `FactSource`, `FactId`, `Fact`, `FactSheet`, `VerdictState`, errors; test:
  `config/insights.yaml` attributes ⊆ `Metric`. Package `__init__.py` with the layer docstring (012 S3c format).
- [ ] T311 `narration/facts.py` `fact_sheet(computed, case) -> FactSheet` (pure): facts from `Computed.cars` (spec
  values with confidence and source), `tco` (period, per year, items), `criteria`, `race`, case facts (budget, period,
  km); comparisons = the `InsightSet`'s insights keyed by `Metric`; narration-only comparisons for TCO items with
  thresholds in `backend/config/narration.yaml`; verdict state; gaps; `variant_id` → `car#N`. Unit tests on fixture
  `Computed`s incl. `NOT_ENOUGH_DATA`, `SINGLE`, a budget pick.
- [ ] T312 `narration/format.py` `render(value, unit, precision, confidence, lang)`: Babel (`babel` added to
  `backend/pyproject.toml` dependencies), unit and metric labels ru/en/es, kW → PS / л.с. / CV, `≈` for `LOW`, CLDR
  plural for counted words; table test with the source §7 examples.
- [ ] T313 Formatting moves to `render`: `dialog/report_text.py` (`_num`, `_thousands`, `fmt`),
  `application/services/report/facts/display.py`, `dialog/report_wording.py` `thousands` (verify each); the blocks the
  text refers to (spec table, TCO, metric bars) get a `display` string per number; `frontend/src/lib/util.ts` and
  `frontend/src/components/blocks/ValueRetention.tsx` show `display` when present (spec §H D8). Behaviour diff: the
  Russian thousands separator, "€38.900" → "38 900 €".
- [ ] T314 Inventory CLI `python -m automind.delivery.cli.narration inventory` (`delivery/cli/narration.py`, beside
  the other CLIs; read-only, through a port): numbers in the last 200 assistant reports (`chat_messages`), each matched to a fact or an operation of the sheet rebuilt from the
  turn's case; unmatched kinds become facts or are listed as dropped (spec §H D5 needs this list). Result in the PR.
- [ ] T315 Record: port `NarrationLog` (`application/ports.py`: `record`, `for_turn`; raises `StoreUnavailable`),
  repository in `chat/infrastructure/`, Alembic migration `narration_checks` (key `(turn_id, kind, shown)`, upsert) +
  `narration_fact_sheets` (by hash); both under `chat` in `scripts/table_owners.yaml`; retention per §H D11. The
  report and answer nodes record the sheet, the request, the old text and the **old guard's** findings (rule, sentence)
  after the model call; a write error → ERROR log + `automind_narration_record_errors_total`, reply goes on (test).
- [ ] T316 Properties (Hypothesis, `backend/tests/unit/chat/application/services/narration/`): random sheets → every
  rendered number equals the rounded fact.

## N3 — Writer and layers 1–3 in the shadow (PR 3; after N2 and 013 S4)

- [ ] T320 `narration/placeholders.py`: grammar of spec §D2 (module-level regex), parse + validate (layer 1: id
  exists, same metric and unit for operations, no `pct`/`ratio` on `YEAR`, division by zero) + evaluate; one test per
  rule.
- [ ] T321 `narration/numerals.py` (numeral dictionary ru/en/es + allowed phrases) and layer 2 in
  `narration/checks.py`: digits outside placeholders and the sheet's car/version names, numerals in words.
- [ ] T322 Layer 3 in `narration/checks.py`: the claim table of spec §D3 incl. `VerdictState`, `best_if_budget`,
  `RECOMMEND.condition`, the sign check, `unverifiable`; a valid and a violating `WriterOutput` per row.
- [ ] T323 `narration/writer.py`: the facts table (source §5.1 format), the narration rules appended to
  `dialog/prompts/reporter_*.md` / `answerer.md` by code, `structured(role, WriterOutput, …)`; `WriterOutputInvalid`
  wraps the gateway's `ValueError`; one retry with the validation error; then blocks + template verdict.
- [ ] T324 `Narrator.write` (≤ 40 lines, `narration/service.py`) for layers 1–3 + rendering; request built from
  `Intent` (013 T043), not `request_kind`.
- [ ] T325 Shadow per spec §H D5 (default: nightly offline run over the day's recorded sheets, capped by
  `narration.shadow_max_texts` in `backend/config/narration.yaml`; results as rows with `shown=false`).
- [ ] T326 Attack set `backend/tests/eval/narration/` (`cases.yaml`, `schema.py`, `test_cases.py`, README, like
  `backend/tests/eval/understanding/`): ≥ 100 cases ru/es/en; offline cases (ready `WriterOutput`) run every commit;
  live cases `-m live`, nightly with 013 T006.

## N4 — Judge and repair ladder in the shadow (PR 4)

- [ ] T330 Role `narration_judge` in `backend/config/models.yaml` (spec §H D1); `dialog/prompts/narration_judge.md`;
  `narration/judge.py` with `JudgeOut`; time limit from config; provider failure / timeout / budget →
  `judge_skipped` with the reason; served models of writer and judge recorded, coincidence flagged.
- [ ] T331 `narration/repair.py`: rewrite of the paragraph with findings (one per text) → layers 1–3 again →
  `narration/templates.py` (one template per `ClaimKind` × ru/en/es) → removal with notice (spec §H D3); the failures
  table of spec §D5 as code, no `except Exception`; a test drives each row.
- [ ] T332 Judge set `backend/tests/eval/narration/judge_cases.yaml` (hand-labelled, ≥ 60 sentences ru/es/en):
  precision ≥ 0.9, recall ≥ 0.85, run `-m live` on a judge model change.
- [ ] T333 Metrics `automind_narration_findings_total`, `_repairs_total`, `_judge_disagreement_total`, `_cost_eur`
  (`shared/infrastructure/metrics/prom.py`), log line `narration.checked`; alert in
  `deploy/prometheus/automind-rules.yml`; `guard_removed` signal emitted on step 2/3.
- [ ] T334 Reference reports: 20–30 exported from `narration_checks` to `backend/tests/eval/narration/reference/`
  (user words masked); nightly: no layer 1–3 findings, verdict and key comparisons present, step 2/3 ≤ 5 %.

## N5 — Switch and delete the guard (PR 5, may split per kind; after N4's acceptance)

- [ ] T340 Answer switched to `Narrator.write` (incl. `ANSWER_AND_REASK`; the re-ask stays code text);
  `dialog/nodes/report.py` `answer_node` ≤ 30 lines; golden dialogues with a scripted `WriterOutput`.
- [ ] T341 Report switched (REPORT, RESCORE; `critique_lead` stays code); owner's blind comparison on 20 pairs; p95
  and cost measured on pre-prod.
- [ ] T342 `general` and `alternatives`: layer 2 per spec §H D6 (measure first); the "no figures about specific
  models" rule in `dialog/prompts/general.md`.
- [ ] T343 Deleted: `dialog/guard.py`, `report_check`, `write_report`/`write_answer` checks, `CheckInput`
  (`application/services/report/contracts.py:110-118`, verify) and its builder (`stages/verdict.py:84-87`), the
  `facts` JSON's code sentences no longer read; tests moved to the narration package; 12 lines removed from
  `scripts/structure_baseline.txt` (guard 10, report_writer 2).
- [ ] T344 Edits to sibling specs: 013 T035 `turn show` prints the narration row; 013 spec §C non-goal points to 016
  for the guard (`coverage-audit.md` §E1–E4).
- [ ] T345 `docs/next-session.md` updated; acceptance list of spec §E ticked with numbers.
