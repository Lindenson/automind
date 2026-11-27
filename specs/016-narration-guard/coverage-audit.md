# Coverage audit: narration guard draft → the code (and specs 012–015)

Date: 2026-11-27. Read-only on code; every claim below was checked on branch `016-narration-guard-spec` (= main
`18108c8` for code). Paths are under `backend/src/automind/` unless they start with `backend/`, `frontend/`,
`scripts/` or `specs/`. Source: `specs/016-narration-guard/source-spec.md` (§1–§12, a teammate's draft, written against
an archive "without code outside": §12 Q1, Q4).

Verdicts: **true** / **partly** / **wrong**, with file:line. "Means" says what follows for spec 016.

## 0. General remarks

| # | Remark | Consequence |
|---|---|---|
| G1 | The draft's description of the guard is right in substance: numbers are checked as an unlabelled bag, contradictions by word lists, the fix is a silent removal (§A). Two details are wrong: a budget stop is **not** swallowed by the rewrite (R8), and a correct difference is **kept** when it is a meaningful insight's difference (§B row 5). | The problem statement stands; spec §B restates it with the verified evidence. |
| G2 | The §1 table was reproduced with the real guard functions (§B). 6 of 8 rows behave as the draft says; row 2 is not "kept" (a word rule catches it, by luck of the data) and row 5 is kept with the real facts. Three further failures the draft did not list: the absence and below-threshold rules never fire for 6 of the 16 insight attributes (key mismatch), the tie-winner rule needs the full car name, and `check_numbers` accepts digits from model codes in the labels ("D-4D" lets "4 %" through). | Step 1 (quick fixes) gets three more cheap fixes (spec §F N1). |
| G3 | The draft's `Verdict` (winner \| tie) and `Comparison` are simpler than the code's: `domain/verdict/verdict.py:80-96` has `pick_car_id`, `tie`, `not_enough_data`, `best_if_budget`, `limits`, `trade_off`, `would_change`, `other_profile`; `Insight` (`domain/verdict/insights.py:101-119`) already *is* a comparison (`tiers`, `better_car`, `threshold`, `meaningful`). | `FactSheet` reuses `Insight`/`Verdict` instead of re-deriving them; the claim table gets rows for `not_enough_data`, `best_if_budget` and the trade-off (spec §D3). |
| G4 | Three of the draft's "three texts" are not alike: `alternatives` has **no data at all** (the cars did not fit; it suggests kinds of cars from model knowledge, `dialog/nodes/feasibility.py:93-108`), and `general` has none either. | Narration covers `report` and `answer` (incl. 013's `ANSWER_AND_REASK`); `alternatives` and `general` get layer 2 (no bare numbers) only (spec §D7, D6). |
| G5 | The draft's metric names (`price`, `reliability`, `maintenance`) are not the code's keys (`official_price_es`, `reliability_score`; there is **no** maintenance comparison anywhere). Power is stored and compared in kW, shown as PS / "л.с." / CV. | `Metric` = the keys of `config/insights.yaml` + the TCO item kinds; conversion kW → PS is the renderer's (spec §D2). |
| G6 | The module path `chat/application/services/narration/` fits the layout (the report service is `chat/application/services/report/`), but the import contract forbids `chat.application` → `chat.dialog` (`backend/.importlinter:58-70`), and all wording (units, labels, phrases) lives in `chat/dialog/report_text.py` and `phrases.py`. | The unit/metric label tables move to the narration package (application), not imported from the dialog (spec §D1). |

## A. Verification of the draft's claims (§1 "how it works now", R1–R8, §2 numbers)

| Claim | Verdict | Evidence | Means |
|---|---|---|---|
| guard.py checks model-written numbers and claims by regex and word lists | **true** | `chat/dialog/guard.py` (268 lines): `_NUM`/`_CHECKED_RE` l.13-17, word tables l.98-155 | — |
| §1.1 code computes facts and blocks, the model writes text from facts | **true** | `chat/application/services/report/service.py:39-68` (`Computed`: blocks, facts, verdict, insights, check); `chat/dialog/report_writer.py:24-47` (`write_report`), `:93-101` (`explain`, no tools) | — |
| §1.2 `check_numbers`: numbers of facts, blocks and the card in one set | **true** | `report_writer.py:43` `allowed = numbers_in(comp.facts) \| numbers_in(comp.blocks) \| numbers_in(case_summary(case))`; plus the integers 1..N cars, `guard.py:76` | the "card" is `case_summary` (`report_writer.py:69-82`), which writes the car's year ("~2021") |
| a sentence with a number outside the set is removed | **true** | `guard.py:73-90`; no rewrite for numbers — they are dropped before `report_check` runs (`report_writer.py:44-45`) | — |
| tolerance 0.5 % | **true (with a floor)** | `guard.py:62` `abs(x - a) <= max(0.051, 0.005 * abs(a))`: 205 vs 204 passes (tolerance 1.02) | step 1 replaces it (spec §F N1) |
| `ALWAYS_OK` = 0, 60, 62, 100, 200, 400 | **true** | `guard.py:18` (comment: 0-100 km/h, 0-200, 400 m, 0-62 mph) | removing it needs the metric-name phrases stripped first, or every "0–100 км/ч" sentence dies (spec §F N1) |
| §1.3 `report_violations`: four rules on ru/en/es word lists (absence, sub_threshold, tie_winner, saving_costlier) | **true** | `guard.py:222-244`; rule names `guard.py:180` (a string, not an enum) | — |
| §2 "8 word lists on 3 languages" | **true (8 named tables, 175 words + 15 regex alternatives)** | `_ABSENCE` 17 (en 6 / ru 6 / es 5), `_COMPARATIVE` 22 (9/7/6), `_WINNER` 17 (7/6/4), `_SAVING` 22 (10/6/6), `_WITHOUT_DEPRECIATION` 11 (3/5/3), `_NEGATION` 13 (7/4/2, "no" shared en/es), `TOPIC_WORDS` 14 topics / 73 words (≈ 28/28/17), `_REFERENCE` regex 15 alternatives (en 8, ru 4, es 3); `guard.py:98-155` | target 0 (only the numeral dictionary of layer 2 stays) |
| §1.4 violations → one rewrite → if it fails, sentences removed silently | **true for the report, wrong for the answer** | report: `report_writer.py:104-128` (one rewrite of the **whole** text, then `drop_sentences`); answer: no rewrite, `drop_sentences` directly (`report_writer.py:63-65`) | the repair ladder rewrites a paragraph, not the text |
| R1 the model writes numbers itself | **true** | `report_writer.py:93-101`; the facts are JSON with pre-formatted strings (`facts/display.py:43-63`) and code-written sentences (`report_text.py:277-285`, `stages/present.py:77-94`) | — |
| R2 numbers as a bag, no car/metric/unit | **true** | `numbers_in` flattens JSON to floats (`guard.py:48-55`); a digit of a model code in a label enters the bag (`_NUM_RE` has no model-code look-behind, unlike `_CHECKED_RE`, `guard.py:15` vs `:17`): "D-4D" admits "4" | §B extra probe |
| R3 derived numbers are nobody's | **partly** | a meaningful insight's difference **is** in the facts (`report_text.py:280-282` "лучше на €3.600"), so "3 600 €" passes; ratios, percentages, sums and below-threshold differences are not, and are removed | §B row 5 |
| R4 contradictions by words; each miss patched by a new word (chat 5821ac77, reviewer 2026-11-03) | **true** | `guard.py:136-147` (comment cites 5821ac77), `:22-23`, `:97`; `TOPIC_WORDS` keys do not match 6 insight keys (`reliability_score`, `max_torque`, `top_speed`, `measured_0_100`, `rear_legroom`, `euro_ncap_stars`; `backend/config/insights.yaml:8-25` vs `guard.py:109-134`), so absence and below-threshold never fire for them | §B probes 9, 12 |
| R5 the fix is a silent removal | **true** | `log_removed` (`report_writer.py:85-90`): `outcomes.note("guard_removed")` + a log line; docstring: "an operator signal, not a message to the user (reviewer 2026-11-03)". The user notice `guard.removal_notice` existed and was deleted as zero-caller by spec 012 T020 (`specs/012-refactoring/tasks.md:60`) | a user notice reverses a reviewer decision → owner's D3 |
| R6 sentences split at the period ("л.с.", "т.д.") | **true** | three splitters: `guard.py:84` and `:252` `(?<=[.!?])\s+`, `:157` `_SENT` (+ newlines); reproduced: "Prado — 204 л.с. и 9,9 л на 100 км, это много." → "Prado — 204 л.с." | — |
| R7 report and answer checked differently; "one rule of four in the answer" | **true, and incomplete** | answer: `check_numbers` + only `saving_costlier` (`report_writer.py:62-65`), no rewrite. Not said by the draft: `general` (`nodes/report.py:68-79`) and `alternatives` (`nodes/feasibility.py:93-108`) are **not checked at all**; the asker's acknowledgement (`application/services/interpretation/ask.py:79,378`) is model text to the user, unchecked (it restates the user's own words; `keep_user_names` only) | spec §D7 |
| R8 `except Exception` in the rewrite turns bugs **and the exhausted budget** into removal | **partly** | `report_writer.py:122-125`: `except BudgetExceeded: raise` comes first, so a budget stop propagates; every other exception (a bug, a bad request, a provider failure) becomes `drop_sentences`. `report_check` also takes `comp: Any` (`:105`) | step 1 narrows it to provider failures (`shared/contracts/provider_failure.py`, `chat/dialog/retry.py:11-13`) |
| §9 "today only the count of removed sentences is written (log_removed)" | **true** | `report_writer.py:85-90`; the signal `guard_removed` feeds `FailureClass.BAD_TEXT` (`observability/domain/outcome.py:53`) | the new record keeps that signal (spec §D6) |

## B. Reproduction of the §1 table (no DB, no model)

Script (throwaway, kept outside the repo): the session scratchpad `guard_repro/repro_s1.py`, run with
`cd backend && uv run python <script>`. It calls the real `check_numbers`, `numbers_in`, `report_violations` and
builds the insights with the real `insights.build` over `backend/config/insights.yaml`, and the facts as
`writer_summary` shapes them (spec values as `display` writes them, ownership cost as `ownership_facts`, the insight
texts by `report_text.reason_text` in Russian), the case summary with "~2021". Data: Sorento 42 500 €, 6.6 l/100 km,
169 kW (230 PS), 2021, period total 31 800 €; Prado 38 900 €, 9.8 l, 150 kW (204 PS), period total 30 600 € (so Sorento
is costlier over the period); verdict tie; reliability about the same. `CheckInput` as `stages/verdict.py:84-87`
builds it. The draft's own run evidently used a bare value bag (no insight texts); both are shown.

| # | Model text | Draft: result | Real facts, **report** path | **Answer** path | Verdict |
|---|---|---|---|---|---|
| 1 | «2. Prado — 205 л.с.» (data: 204) | kept | kept (tolerance 1.02) | kept | **true** |
| 2 | «Sorento обходится на 400 € в год дешевле» | kept (400 in `ALWAYS_OK`) | number passes (`ALWAYS_OK`), but `saving_costlier` fires (Sorento is costlier over the period, "дешевле" in `_SAVING`) → whole-text rewrite → removed if repeated | removed silently | **partly**: the number half is right; the sentence is caught only because Sorento happens to be the costlier car. With Sorento cheaper over the period it is kept |
| 3 | «Sorento стоит 2021 евро в месяц» | kept | kept (2021 from the case summary) | kept | **true** |
| 4 | «Расход у Sorento около двенадцати литров» | kept | kept | kept | **true** |
| 5 | «Разница в цене — 3 600 €» (correct) | removed | **kept**: the price insight is meaningful (9.3 % ≥ 5 %), its text carries "лучше на €3.600". Removed with the bare bag | kept | **partly**: true for derived numbers that no insight text carries — «в 1,5 раза меньше», «на 9 % меньше», a below-threshold difference: all removed |
| 6 | «О надёжности Prado мы знаем мало» (data exists) | not caught | not caught | not checked | **true**; worse: «О надёжности Prado нет данных» is not caught either (`reliability` ≠ `reliability_score`) |
| 7 | «Обе хороши, но я бы взял Prado» (tie) | not caught | not caught | not checked | **true**; worse: «Обе хороши, но лучший выбор — Prado» ("лучший выбор" is in `_WINNER`) is not caught: the rule needs the full name "Toyota Land Cruiser Prado" (`guard.py:242`) |
| 8 | «Sorento экономичнее в обслуживании» | falsely caught | caught (`экономи*`, Sorento costlier over the period) → rewrite → removed | removed | **true**; note there is no maintenance comparison in the data, so whether it is false cannot be decided by any check today |

Extra probes (same run):

| Text | Result | Shows |
|---|---|---|
| «По надёжности Prado лучше» (reliability tie) | not caught | R4: `sub_threshold` misses `reliability_score` |
| «Prado — 204 л.с. и 9,9 л на 100 км, это много.» | → «Prado — 204 л.с.» | R6: a fragment survives the split at "л.с." |
| «Разница в стоимости владения — 1 200 €, это 4 %.» | kept (4 % is wrong: 3.9 %) | R2: "4" enters the bag from the label "2.8 D-4D" |
| «Sorento расходует в 1,5 раза меньше.» | removed (correct: 9.8 / 6.6 = 1.48) | R3 |
| «Sorento обходится на 450 € в год дешевле без учёта потери стоимости.» | kept | the "without depreciation" escape works when the model writes it |

Count for §2 "made-up numbers that pass": of the four made-up numbers (rows 1–4), three reach the user unchanged in both
paths; row 2's number passes the number check and is stopped by an unrelated word rule.

## C. The draft's assumptions about code "outside the archive"

| Assumption | Verdict | Evidence | Means |
|---|---|---|---|
| §12 Q1 a role mapping exists (models.yaml) | **true** | `backend/config/models.yaml`: `reporter`, `answerer` = `gemini-3.6-flash` (l.10-11), `general` = `gemini-3.1-flash-lite` (l.12); env `MODEL_<ROLE>` (l.1); fallbacks l.35-37: the reporter's chain **ends in `gemini-3.1-flash-lite`**; a role `blame_judge` already exists (engine, l.23). The engine's gated model overrides cover engine roles only (`backend/config/agents.yaml:55-60`) | the judge is a new role `narration_judge`; the served models of writer and judge are recorded (`served(role)`, `shared/infrastructure/llm/gateway.py:196`) and a same-model run is flagged, because a fallback can make them equal (D1) |
| §12 Q4 acquisition writes texts that reach the user unchecked | **partly** | the engine's extractors write review texts and issue descriptions (`acquisition/api/car.py:96-117`) that the blocks show with their excerpt and source (`application/services/report/blocks/reviews.py:32`); they quote sources, they are not narration over our facts. No engine text reaches the chat reply | out of scope; recorded as D7 |
| `Computed` is the source of the FactSheet | **true, but loosely typed** | `application/services/report/contracts.py:120-134`: typed `verdict`, `insights`, `tco`, `criteria`, `race`, `cars`; `facts` is `JsonObject` with code-written sentences (electric lines, break-even years, profile focus, used-car lines, `stages/present.py:77-94`) | the builder reads the typed members, never `facts`; the code-written sentences become facts or are dropped — inventory in N2 (D5) |
| `persist_computations` already stores the facts | **wrong** | it stores the TCO estimates and the race only (`application/services/report/computations.py:16-29`, tables `tco_estimates`, `simulations`) | the fact sheet is stored by the new record (spec §D6) |
| `OutcomeRecorder` writes the next turn's complaint/correction | **true** | `chat/dialog/turn/outcome.py` (`OutcomeRecorder`, created in `dialog/runner.py:52`); `OutcomeStore.patch_previous` / `add_signal` (`application/ports.py:296-305`); `relation_next` complaint → `BAD_TEXT` (`observability/domain/outcome.py:53`) | the "flag the check record" hook is a join on `turn_id` at read time, not a second writer (spec §D6) |
| formatting is spread over `report_text` and the blocks | **true, and wider** | `chat/dialog/report_text.py:220-274` (`_num`, `_thousands`: ru and es both "48.500", `fmt`: "€38.900"), `application/services/report/facts/display.py:43-63` ("42.500 €" in every language), `shared/vehicle/units.py:207` ("169 kW (230 PS)"), `chat/dialog/report_wording.py:37`, f-strings in the domain (`domain/cost/tco/items.py:49,159,280-308`), and the **frontend** formats numbers itself (`frontend/src/lib/util.ts:82` en-US, `frontend/src/components/blocks/ValueRetention.tsx:8` es-ES) | "one formatter for text, tables and cards" covers the backend; the frontend is a decision (D8). Russian output changes from "42.500" to "42 500" |
| Babel, pymorphy3, Hypothesis are available | **partly** | Hypothesis: dev dependency (`backend/pyproject.toml:40`). Babel 2.18 is installed only **transitively** (`courlan` → `babel`, `backend/uv.lock:515`), not declared. pymorphy3: absent | N2 declares `babel`; pymorphy3 is avoided (D4) |
| structured output for the writer | **true** | `LLM.structured(role, schema, …)` (`shared/contracts/llm.py:12-17`); a parse failure raises a bare `ValueError` (`shared/infrastructure/llm/gateway.py:201-202`) | a named error for "schema not matched" is needed for the one retry (code-shape "errors by type") |
| metric names `narration_*` | **partly** | metrics are `prometheus_client` with prefix `automind_` (`shared/infrastructure/metrics/prom.py:24`) | `automind_narration_*` |

## D. Requirement coverage (draft § → spec 016)

| § | Requirement | Status | Where in spec 016 |
|---|---|---|---|
| 2.G1 | no number can be made up | kept | §D2–D4, N3 |
| 2.G2 | differences, %, ratios as operations | kept | §D2 |
| 2.G3 | conclusions as typed claims | kept, claim table extended (G3) | §D3 |
| 2.G4 | judge | kept, role named, model recorded | §D5, N4 |
| 2.G5 | repair instead of removal | kept; the user notice is D3 | §D5 |
| 2.G6 | one pipeline for report, answer, alternatives | **changed**: report + answer; alternatives/general layer 2 only (G4) | §D7 |
| 2.G7 | full trace | kept, as one table + port | §D6 |
| 2 criteria | acceptance numbers | kept; "8 lists → 0" kept; baselines restated from §B | §C |
| 4.1 | `Fact`, `FactSheet`, `Unit` | kept; `Verdict`/`Comparison` reuse the domain (G3); `subject` is the case's car key; `source`/`confidence` as enums | §D1–D2 |
| 4.2 | placeholders, closed grammar | kept; `{fact}`, `{diff}`, `{pct}`, `{ratio}`, `{sum}`, `{name}` | §D2 |
| 4.3 | claims | kept + `BEST_IF_BUDGET`-aware `WINNER`, `NOT_ENOUGH_DATA` verdict, `condition` field for `RECOMMEND` declared | §D3 |
| 5 | writer via structured output; facts as a table | kept | §D4 |
| 6.1 | layer 2 + numeral dictionary | kept; the dictionary is the one word table left | §D4 |
| 6.2 | layer 3 table | kept + rows for the verdict states; `CHEAPER(maintenance)` needs a maintenance comparison (none exists, G5) | §D3 |
| 6.3 | judge when / how | kept; answer condition is D2 | §D5 |
| 7 | one `render()`, Babel, precision, ≈ for low confidence | kept; frontend D8 | §D2 |
| 8 | repair ladder and failures table | kept; "temporary provider error" = `TRANSIENT` of `provider_failure.py`; bug → turn FAILED through the existing ending | §D5 |
| 9 | `narration_checks`, metrics, feedback link | kept; owner `chat`; retention as 015 D2 | §D6 |
| 10 | tests and eval sets | kept; attack set beside 013's eval set | §E |
| 11 | five-step migration | kept as N1–N5 | §F |
| 12 | open questions | D1–D5 | §H |

## E. Overlaps and conflicts with specs 012–015

| # | Spec | What | Resolution (proposed edit) |
|---|---|---|---|
| E1 | 013 | Non-goal "research, report and guard are untouched; code checks of model output (numbers in the text…) stay" (`specs/013-dialogue-quality/spec.md:84-85`) | holds for 013; 016 owns the guard. No edit to 013 needed beyond a pointer. |
| E2 | 013 | T043 moves the `request_kind` readers in `report_writer` to `Intent` (`specs/013-dialogue-quality/tasks.md:175-178`); S4 adds `ANSWER_AND_REASK` (T041) — a new answer shape | N3–N5 come after 013 S4; the narration request takes the goal from `Intent`, never `request_kind`; `ANSWER_AND_REASK` is narrated as `answer` (the re-ask is code text) |
| E3 | 013 | T035 `turn show` renders one turn from its records | add `narration_checks` to `turn show` (one more record, read through the `NarrationLog` port) |
| E4 | 013 | S6 self-diagnosis signals; `guard_removed` → `BAD_TEXT` | the signal is kept, emitted when a repair reached `template` or `removed` (spec §D6) |
| E5 | 014 | report/answer are `@node`s with typed `ComposeIn`/`AnswerIn`/`ReportOut`/`ReplyOut` (`dialog/nodes/report_io.py:16-55`); C2 rule: persist after the model call, one conflict retry, `Retry.PROVIDER` | the narration record is written after the text, keyed `(turn_id, kind)`, upsert: a retried node writes no duplicate. No new board key: narration writes through its port, not the state. C3's sections do not change the node's `Out` (reply text) |
| E6 | 015 | PL3 introduces the per-pass record pattern (`DecisionLog` port, upsert key, retention, `why` CLI) | 016's `NarrationLog` copies the pattern (port in `application/ports.py`, `StoreUnavailable` only, table owner `chat`, 90 days) |
| E7 | 012 | code-shape: no `Any`, ≤ 40-line public functions, states as enums, word tables not inside logic modules, regex compiled at module level in a contracts section, no `except Exception` without reason; `guard.py` carries 10 structure debts (`scripts/structure_baseline.txt:795-800,1105-1107,1157`) and `report_writer.py` 2 `word` debts (`:1348-1349`) | the narration package is born at 0; N5 deletes the 12 baseline lines. Location `chat/application/services/narration/` matches the report service (`chat/application/services/report/`); it may not import `chat.dialog` (`backend/.importlinter:58-70`), so unit labels and templates live in the package, and the nodes stay ≤ 30 lines |
| E8 | 012 | A4c onward is the acquisition area | no file overlap with 016 (chat only); N2–N5 may run beside A4c+ |

## Decisions pending

D1–D8 in spec §H.
