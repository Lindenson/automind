# Spec 016 — Narration: facts by id instead of numbers, typed claims instead of word lists

**Branch**: `016-narration-guard-spec` · **Created**: 2026-11-27 · **Status**: Draft, awaiting the owner's approval (§H)

**Input**: a teammate's draft "Спека: проверка текста модели (guard) — факты вместо чисел, утверждения вместо слов"
(2026-11-27), saved verbatim in `source-spec.md`; checked against the code on 2026-11-27 (§B, `coverage-audit.md`).
Related: spec 013 (understanding; `Intent`, `ANSWER_AND_REASK`, `turn show`), spec 014 (node contracts: `@node`,
typed `In`/`Out`, retry purity), spec 015 (the per-pass record pattern), spec 012 code-shape contract
(`specs/012-refactoring/contracts/code-shape.md`).

**Goal in one sentence**: the model never writes a number and never makes an undeclared conclusion — it refers to
facts by id and declares its claims; code renders the numbers, checks the claims against the data, repairs what is
wrong and records every check.

---

## A. Why

The reporter and the answerer write numbers and conclusions themselves; `chat/dialog/guard.py` then tries to tell
truth from invention by matching numbers against an unlabelled bag and conclusions against 8 word tables. It lets
made-up numbers through (a wrong horsepower, a year written as a price), cuts correct comparisons (ratios,
percentages), misses contradictions phrased in other words, and repairs by deleting sentences silently, sometimes
leaving a fragment. Every miss has been patched with another word (chat 5821ac77, reviewer 2026-11-03), and the
answer path runs one rule of four.

## B. Evidence (verified in code 2026-11-27)

Paths under `backend/src/automind/chat/`. Full verdicts: `coverage-audit.md` §A; the §1 table reproduced: §B there.

| # | Fact | Where |
|---|---|---|
| B1 | Numbers are checked as a bag of floats from facts, blocks and the case summary, plus 1..N cars; tolerance `max(0.051, 0.5 %)`; `ALWAYS_OK = {0, 60, 62, 100, 200, 400}` | `dialog/report_writer.py:43`; `dialog/guard.py:18,48-90` |
| B2 | Reproduced: "Prado — 205 л.с." (data 204), "стоит 2021 евро в месяц" (2021 is the year), "около двенадцати литров" pass; "в 1,5 раза", "на 9 %" (both correct) are removed; "4 %" passes because "D-4D" in a label puts 4 in the bag | `coverage-audit.md` §B |
| B3 | Contradictions: 4 rules over 8 tables (175 words + 15 regex alternatives, ru/en/es). The topic keys miss 6 of the 16 insight attributes (`reliability_score`, …), so "о надёжности нет данных" and "по надёжности лучше" (a tie) pass; the tie-winner rule needs the full car name | `guard.py:98-155,222-244`; `backend/config/insights.yaml:8-25` |
| B4 | Repair: numbers are dropped with no rewrite; word-rule violations get one rewrite of the **whole** text, then the sentences are dropped; any exception except `BudgetExceeded` becomes a drop (`except Exception`, `comp: Any`) | `report_writer.py:44-45,104-128` |
| B5 | Silent: removal is a log line and the signal `guard_removed` (→ `BAD_TEXT`); the user notice was removed in 2026-11 (reviewer 2026-11-03; 012 T020 deleted `guard.removal_notice`) | `report_writer.py:85-90`; `observability/domain/outcome.py:53` |
| B6 | Three sentence splitters at `[.!?]`; "л.с." cuts a sentence and a fragment survives | `guard.py:84,157,252` |
| B7 | Answer: number check + `saving_costlier` only, no rewrite; `general` and `alternatives` are not checked at all | `report_writer.py:50-66`; `dialog/nodes/report.py:68-79`; `dialog/nodes/feasibility.py:93-108` |
| B8 | The data already holds the comparisons and the verdict, typed: `Insight` (tiers, `better_car`, threshold, meaningful), `Verdict` (pick, tie, not enough data, best if budget, trade-off); there is **no maintenance comparison** | `domain/verdict/insights.py:101-119`; `domain/verdict/verdict.py:80-96` |
| B9 | Numbers are formatted in ≥ 6 places, inconsistently (ru "48.500", "€38.900", "42.500 €", "169 kW (230 PS)"), and the frontend formats too | `dialog/report_text.py:220-274`; `application/services/report/facts/display.py:43-63`; `shared/vehicle/units.py:207`; `frontend/src/lib/util.ts:82` |
| B10 | Structured output exists (`LLM.structured`); its parse failure is a bare `ValueError` | `shared/contracts/llm.py:12-17`; `shared/infrastructure/llm/gateway.py:201-202` |
| B11 | Babel is installed only transitively (via `courlan`); pymorphy3 absent; Hypothesis a dev dependency | `backend/uv.lock:515`; `backend/pyproject.toml:40` |
| B12 | `persist_computations` keeps TCO estimates and the race only — no record of the facts or of the text checks | `application/services/report/computations.py:16-29` |

Corrections to the source: a budget stop already propagates (B4); a meaningful insight's difference is kept today (B2,
row 5 of the §1 table); row 2 is caught by a word rule, by luck of the data; `alternatives` has no facts to narrate
(G4 in the audit); metric keys and units follow `config/insights.yaml` (kW, not hp).

## C. Goals

1. **No made-up number by construction**: every number in a data text comes from a fact with an id or from an
   operation over facts computed by code.
2. **Comparisons allowed and right**: difference, percentage, ratio, sum are operations of the grammar.
3. **Conclusions checked by structure**: winner, tie, better, cheaper, no data, recommend are typed claims checked
   against the verdict and the insights, independent of language and wording.
4. **Meaning checked on top**: an independent judge model looks for undeclared conclusions in the rendered text.
5. **Repair, not removal**: rewrite the paragraph → a template sentence from data → removal with a notice. No
   fragments ever.
6. **One pipeline** for report and answer (incl. `ANSWER_AND_REASK`); `general` and `alternatives` get the bare-number
   layer (§D7).
7. **Full record**: every check and every repair written, replayable.

Non-goals: no change of the report's calculations (TCO, scores, insights, verdict) — only how they reach the text;
no style or tone checks; no 100 % guarantee on meaning (numbers are guaranteed by construction, conclusions checked
with measured precision).

Measurable (baselines verified, §B):

| Criterion | Now | Target |
|---|---|---|
| Made-up numbers reaching the user (attack set) | 3 of 4 in the §1 table (B2) | 0 |
| Correct comparisons cut by the check | ratios, percentages, below-threshold differences (B2) | 0 |
| Contradictions of the verdict missed (reference reports) | unknown; 3 known misses (B3) | ≤ 1 % of reports |
| False positives of the claim check | unknown; row 8 of the §1 table | ≤ 3 % of sentences |
| Texts with fragments after repair | yes (B6) | 0 |
| Word tables for contradictions | 8 (B3) | 0 (only the numeral dictionary of layer 2) |
| Data texts with a check | report full, answer 1 rule of 4, general/alternatives none (B7) | report, answer: 4 layers; general/alternatives: layer 2 |
| Extra cost per report (judge) | 0 | ≤ 15 % of the writing cost |
| Structure debts of guard/report_writer | 12 baseline lines | 0 |

## D. Design

As the source §3–§9, with the deviations named here (each also in §H when it needs the owner).

### D1. Package and contracts

`chat/application/services/narration/` (beside `services/report/`; may not import `chat.dialog`, so unit labels,
templates and the numeral dictionary live in the package):

| Module | Owns | Deterministic |
|---|---|---|
| `contracts.py` | `Unit`, `Metric`, `FactSource`, `FactId`, `Fact`, `FactSheet`, `VerdictState`, `ClaimKind`, `Claim`, `Sentence`, `WriterOutput`, `Layer`, `FindingRule`, `Finding`, `RepairStep`, `Repair`, `NarrationKind`, `Narrated`; errors `PlaceholderError`, `WriterOutputInvalid`, `NarrationBug` | — |
| `facts.py` | `fact_sheet(computed, case) -> FactSheet` | yes |
| `placeholders.py` | the closed grammar: parse, validate (layer 1), evaluate operations | yes |
| `checks.py` | layers 1–3 as pure functions `(WriterOutput, FactSheet) -> list[Finding]` | yes |
| `numerals.py` | the numeral dictionary ru/en/es and the allowed phrases ("одна из машин") — the one word table | data |
| `format.py` | `render(value, unit, precision, confidence, lang) -> str`; unit and metric labels ru/en/es | yes |
| `templates.py` | one template per `ClaimKind` × language (repair step 2) | data |
| `writer.py` | the writer call (structured output) | no (LLM) |
| `judge.py` | layer 4 | no (LLM) |
| `repair.py` | the ladder | step 1 LLM, 2–3 code |
| `service.py` | `Narrator.write(kind, sheet, request, lang) -> Narrated`; writes the record | — |

All types frozen pydantic, `extra="forbid"`; closed sets are `StrEnum` (`FactSource`, `Confidence` reuses the domain's
`HIGH | MEDIUM | LOW`); no `Any` in a public signature; modules ≤ 200 lines, public functions ≤ 40; regexes compiled
in each module's contracts section; no `except Exception`. Port `NarrationLog` in `application/ports.py` (raises
`StoreUnavailable` only), repository in `chat/infrastructure/`. The nodes keep ≤ 30 lines and call only
`Narrator.write` (built in the composition root like `ReportService`).

### D2. Facts, placeholders, rendering

- `Fact`: as the source §4.1, with `subject` = the case's car key (`car#N`, `domain/case/delta.py:323`), `"case"` or
  `"verdict"`; the insights' `variant_id`s are mapped to car keys by the builder. `Metric` = the keys of
  `config/insights.yaml` (`official_price_es`, `consumption`, `reliability_score`, …) + the TCO item kinds per year
  (`maintenance_per_year`, `energy_per_year`, …) + `tco_period`, `tco_per_year`; a test asserts the insights keys ⊆
  `Metric`. Units follow the data (power in kW); the renderer shows power as PS / "л.с." / CV.
- `FactSheet` holds the facts, `comparisons: Mapping[Metric, Insight]` (the domain's `Insight`, not a copy), the
  verdict state (D3), `gaps` (from the verdict's gaps and each car's missing rows) and `car_names`. Built only from the
  typed members of `Computed` (`verdict`, `insights`, `tco`, `criteria`, `race`, `cars`), never from `facts` JSON.
- Comparisons the insights do not have (maintenance per year, other TCO items) are computed by the builder for
  narration only, with thresholds in `backend/config/narration.yaml`; `InsightSet` and the verdict do not change
  (non-goal).
- Placeholders exactly as the source §4.2 (`{fact}`, `{diff}`, `{pct}`, `{ratio}`, `{sum}`, `{name}`) and its validity
  rules; a new operation is a spec change. Metric names that contain digits ("0–100 km/h", "400 m") are rendered with
  the fact (`{fact:car#1.accel_0_100}` → "разгон 0–100 км/ч за 8,2 с").
- `render` as the source §7, on Babel (declared as a direct dependency); precision from the fact, worst of the
  operands for operations, `pct` to 1 %, `ratio` to 0.1; `≈`/"около" for `LOW` confidence added by the renderer;
  `diff` unsigned. Russian agreement ("в 1,5 раза", "5 лет") by the CLDR plural category from Babel — no pymorphy3
  (§H D4). The report's blocks and `report_text` move to `render` (N2); the Russian thousands separator changes from
  "." to a narrow space — listed in N2's behaviour diff.

### D3. Claims and layer 3

`ClaimKind` and `Claim` as the source §4.3, `RECOMMEND` with an optional `condition: Metric` (the source names it only
in §6.2). The verdict is read as `VerdictState` = `PICK | TIE | NOT_ENOUGH_DATA | SINGLE` (from `Verdict.pick_car_id`,
`tie`, `not_enough_data`, `InsightSet.single`). Layer 3 table (source §6.2, extended for the code's verdict):

| Claim | Allowed when |
|---|---|
| `WINNER(car)` | state `PICK` and `pick_car_id` is `car` |
| `TIE` | state `TIE` |
| `BETTER(car, m)` | `comparisons[m].meaningful` and `better_car == car` |
| `SAME(m)` | `m` in the insights' ties |
| `CHEAPER(car, m)` | `m` is a money metric and `better_car == car` for that metric (maintenance from its narration comparison) |
| `NO_DATA(car, m)` | `(car, m)` in `gaps` |
| `RECOMMEND(car)` | state `PICK`, `pick_car_id == car`; or `best_if_budget == car` with `condition` = the budget; in a `TIE`, only with a `condition` whose comparison has `better_car == car` |

Plus the sign check of the source (`CHEAPER(car#2, price)` with `{diff:…}` while car#2 is dearer is a finding). A
claim about a metric without a comparison is a finding `unverifiable` (repaired like a wrong claim).

### D4. Writer, layers 1–2

Writer as the source §5: the facts as a table with ids, comparisons, verdict state and gaps; structured output
`WriterOutput` (sentences already split — R6 disappears); the narration rules (source §5.3) are appended by code to
today's `reporter_*` / `answerer` prompts, whose style rules stay. Roles stay `reporter` and `answerer`
(`backend/config/models.yaml:10-11`). A schema mismatch raises `WriterOutputInvalid` (the gateway's bare
`ValueError` is wrapped where the narration calls it) → one retry with the validation error → a report from blocks and
the template verdict with a notice. Layer 1 (structure) and layer 2 (bare numbers: digits outside placeholders and
car/version names from the sheet; numerals by the closed dictionary) as the source §6, no `ALWAYS_OK`, no tolerance.

### D5. Judge and the repair ladder

Judge as the source §6.3: role `narration_judge` (not `judge`: the engine has `blame_judge`), a cheap model other than
the writer's (§H D1); input the rendered text, the sheet and the claims; output `[{sentence_id, problem,
explanation}]`; does not check numbers; runs always for a report, for an answer per §H D2; a provider failure or
timeout → `judge_skipped` (the text already passed layers 1–3). The served models of writer and judge are recorded
(`served(role)`, `gateway.py:196`); a run where they coincide (a fallback) is flagged.

Ladder as the source §8: (1) rewrite only the paragraph with findings, with the findings and the needed facts; the
paragraph passes layers 1–3 again (no second judge); (2) a template sentence from data per `ClaimKind` × language;
(3) removal with a notice only for a sentence without a claim (judge finding) that the rewrite did not fix. At most one
rewrite per text. Failures:

| Failure | Reaction |
|---|---|
| provider failure in `TRANSIENT` or `ProviderUnavailable` (`shared/contracts/provider_failure.py`) | step 2, no retry |
| `BudgetExceeded` in the rewrite or the judge | step 2 / `judge_skipped`; recorded as `budget_exceeded`; the reply is delivered (§H D9) |
| rewritten paragraph fails layer 1 | step 2 for each sentence with findings |
| any other exception (a bug in a check or the renderer) | propagates: the turn FAILS through the existing ending (`dialog/turn/endings.py`) |

The node's `Retry.PROVIDER` still covers the writer's first call (014 C2: nothing is written before it).

### D6. Record and metrics

One row per text in `narration_checks` through `NarrationLog`: `turn_id`, `kind`, `shown` (false in the shadow),
`fact_sheet_hash` (sheets in `narration_fact_sheets` by hash), `writer_output`, `findings`
`[{layer, sentence_id, rule, detail}]`, `repairs` `[{sentence_id, step, before, after}]`, `judge` (model, result or
skipped with the reason), `final_text`, `prompt_version`, `writer_model`, `judge_model`; key `(turn_id, kind, shown)`,
upsert (a retried node writes no duplicate, 014 C2). Table owner `chat` (`scripts/table_owners.yaml`); Alembic
migration; retention 90 days (§H D11). A write failure: ERROR log + `automind_narration_record_errors_total`, the
reply goes on. From N2 the row also records the **old** guard's findings, so the shadow and the baseline have data.

Prometheus (prefix `automind_`): `narration_findings_total{layer,rule,kind}`, `narration_repairs_total{step}`,
`narration_judge_disagreement_total`, `narration_cost_eur{kind,stage}`; alert when the share of texts reaching step 2
or 3 exceeds 5 % for a day (`deploy/prometheus/automind-rules.yml`). The signal `guard_removed` (→ `BAD_TEXT`) is kept,
emitted when a repair reached step 2 or 3. The feedback link of the source §9 is a read-time join: a turn whose next
turn is a complaint/correction (`OutcomeStore.patch_previous`) lists its narration row in the weekly review queue
(013 G7's script) as an attack-set candidate. 013 T035 `turn show` prints the row.

### D7. Which texts

| Text | Today | 016 |
|---|---|---|
| report (incl. RESCORE, critique; the critique lead stays code) | numbers + 4 rules + 1 rewrite | full narration |
| answer (incl. 013 `ANSWER_AND_REASK`; the re-ask is code text) | numbers + 1 rule | full narration |
| alternatives | none; no facts exist (cars did not fit) | layer 2 only (§H D6) |
| general | none; no facts | layer 2 only (§H D6) |
| asker acknowledgement | none; restates the user's words | out of scope |
| engine texts in blocks (reviews, issues) | quoted with source | out of scope (§H D7) |

## E. Testing and acceptance

- Unit (no model, no DB): per rule of layers 1–3 a valid and a violating `WriterOutput` — the finding found and only
  it; the placeholder grammar (each validity rule); `fact_sheet` from fixture `Computed`s (incl. `NOT_ENOUGH_DATA`,
  `SINGLE`, a budget pick); the repair ladder per failure row with a fake LLM (each failure path driven).
- Renderer: a table fact × language → exact string, incl. the source §7 examples and kW → PS.
- Properties (Hypothesis): random sheets + random valid templates → every number in the output equals a rounded fact
  or operation; the ladder never leaves an empty paragraph or a fragment.
- Attack set `backend/tests/eval/narration/` (YAML, beside 013's `tests/eval/understanding/`): 100+ cases ru/es/en —
  the §1 table, the extra probes of `coverage-audit.md` §B, numerals in words, the year as a price, a winner in a tie
  in several phrasings, "cheaper" on several metrics; offline cases carry a ready `WriterOutput` (every commit);
  live cases call the writer (opt-in `-m live`, on every prompt or model change and nightly with 013's run).
- Judge set: hand-labelled sentences → precision ≥ 0.9, recall ≥ 0.85 (on a judge model change).
- Reference reports: 20–30 real comparisons exported from `narration_checks` (fact sheet + request) → fixtures; no
  layer 1–3 findings; the verdict and the key comparisons present (nightly).
- Graph: report/answer golden dialogues pass with a scripted writer returning `WriterOutput`; `graph_shape.json`
  unchanged; retry purity (014) green.

Acceptance before the switch (source §10, kept):
- [ ] The 8 cases of the §1 table and the extra probes handled right.
- [ ] Attack set: 0 made-up numbers, ≤ 1 % missed contradictions, ≤ 3 % false positives.
- [ ] Texts reaching step 2 or 3 ≤ 5 % on the reference reports.
- [ ] Blind readability comparison of old and new on 20 pairs (the owner): new not worse in ≥ 80 %.
- [ ] Report writing p95 ≤ +25 %, cost ≤ +15 %.
- [ ] After N5: `guard.py`, `report_violations`, `CheckInput`, the 8 word tables gone; 12 baseline lines removed.

## F. Steps (one PR each; tasks in `tasks.md`)

| # | Step | When |
|---|---|---|
| N1 | Quick fixes on the old guard (source step 1 + three audit fixes) | now, beside 015 PL2 (§H D10) |
| N2 | `FactSheet`, `render`, the record (with the old guard's findings) | after 013 S7 (or earlier, §H D10) |
| N3 | Writer + layers 1–3 in the shadow | after N2 and 013 S4 |
| N4 | Judge + repair ladder, in the shadow | after N3 |
| N5 | Switch per kind: answer → report; layer 2 on general/alternatives; delete the guard | after N4's acceptance |

N1 content: remove `ALWAYS_OK` after stripping the metric-name phrases ("0–100 км/ч", "0-62 mph", "400 m"); the
tolerance becomes "equal at the precision the text wrote" (205 ≠ 204; "42 500" matches 42 480); `except Exception` in
the rewrite → only provider failures, anything else propagates; the answer gets all four rules and the one rewrite;
the topic map covers every insight key and the tie rule uses the car's aliases; one abbreviation-aware sentence
splitter for all three places; model codes in labels never feed the bag; the user notice on removal if §H D3 says so.

## G. Approved constraints kept

1. 013 order (S3 → S7) and its G-decisions untouched; 016 reads `Intent`, never `request_kind`, once 013 S4 is in
   (`coverage-audit.md` §E2).
2. 014: report/answer stay `@node`s with today's `In`/`Out`; the record is written after the model call, upserted
   (retry purity); no new board key.
3. 015: the record copies `policy_decisions`' pattern (port, `StoreUnavailable`, owner `chat`, 90 days).
4. 012: code-shape and import contracts; the package is born with 0 structure debts; N5 removes guard's 12.
5. Autonomy boundary: the judge's and the writer's models change only in `models.yaml` by a human (the engine's
   gated overrides cover engine roles only, `backend/config/agents.yaml:55-60`).

## H. Owner's decisions (proposed, awaiting the owner)

| # | Question | Proposal |
|---|---|---|
| D1 | (source §12 Q1) Models of writer and judge; where roles map | Writer: `reporter`/`answerer` as today (`gemini-3.6-flash`). Judge: new role `narration_judge` = `gemini-3.1-flash-lite` in `backend/config/models.yaml` (env `MODEL_NARRATION_JUDGE` overrides). The reporter's fallback chain ends in the same model, so the record stores both served models and flags a coincidence; no blocking. |
| D2 | (§12 Q2) Judge on every answer? | As the source: report always; answer when it names more than one car or declares a claim. Revisit with N4's shadow numbers (`narration_judge_disagreement_total` on answers). |
| D3 | (§12 Q3) Notice to the user | No notice for a template replacement (step 2 — the sentence is true, from data); a quiet notice for a removal (step 3) — this reverses the reviewer's 2026-11-03 "operator signal only" for removals, which is why it is asked. N1 adds the same notice to the old guard's removals only if you say yes. |
| D4 | (§9 risk) Russian agreement: pymorphy3? | No new dependency: the renderer's few counted words ("раз", "год", "литр") use the CLDR plural category from Babel; units are abbreviations that do not decline. pymorphy3 only if the blind comparison fails on grammar. |
| D5 | Shadow mode (source step 3: both texts on 10 % of turns) | Offline instead: from N2 every report/answer records its fact sheet and request; the new writer runs nightly over the last day's sheets (capped, e.g. 50 texts ≈ €0.5), no user latency, no doubled turn cost. Inline shadow only if the offline numbers are inconclusive. |
| D6 | (§12 Q5) `general` and `alternatives` | Layer 2 only, measure first: findings logged and counted for 2 weeks (N5), then one rewrite + removal with notice if the rate is above 1 %. The "no figures about specific models" rule is added to the `general` prompt now (alternatives already has it). |
| D7 | (§12 Q4) Engine texts reaching the user | None reach the reply; review texts and issue descriptions are shown in blocks as quotes with their source — out of scope. |
| D8 | Frontend formatting (`frontend/src/lib/util.ts:82`, `ValueRetention.tsx:8`) | N2 adds a `display` string from `render` beside each number of the blocks the text refers to (spec table, TCO, metric bars); the frontend shows it when present. Other frontend formatting later. |
| D9 | Budget stop in the rewrite or the judge | Template / `judge_skipped`, recorded as `budget_exceeded`, the reply is delivered (today the stop fails the turn after the writer has already been paid). |
| D10 | Placement in the agreed order | N1 now, beside 015 PL2: ~1 PR, no model cost, files no 013/014/015 step touches before 013 S4; it stops made-up numbers reaching the owner today (quality first). N2–N5 after 013 S7, beside 012 A4c+ (no file overlap: acquisition). Alternative: N2 right after 015 PL3, so fact sheets accumulate for D5 earlier. |
| D11 | Tables and retention (`narration_checks`, `narration_fact_sheets`) | Both under `chat`; 90 days, deleted daily by the chat retention step (as 015 D2); fact sheets kept while a check row refers to them. |
