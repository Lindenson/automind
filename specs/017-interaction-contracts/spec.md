# Spec 017 — Every interaction has a contract; sources are searched as a pyramid

**Branch**: `017-spec-interaction-contracts` · **Created**: 2026-11-28 · **Status**: Draft, awaiting the owner's
approval (§H)

**Input**: the owner, 2026-11-28, after chat 725e7437 (BMW 320d "not found"): "все взаимодействия с пользователем
покрыть контрактами и улучшить до контрактов и оттестировать. должно работать как часы. и по моделям и по поиску" +
a note on vehicle data sources and a search pyramid ("начать с крупняка и важного, затем за деталями"), kept in
`source-note.md`. Checked against the code and the live sources on 2026-11-28 (§B). Related: spec 005 (intake), 007
(case panel), 010 FR-035–FR-039 (card, Change), 011 (acquisition engine, registry), 013 (understanding: S4 switch,
T012/T013), 014 (node contracts), 015 (policy). Point fixes already merged: PR #163.

**Goal in one sentence**: every way the person can act on the chat has a written contract (what it changes, what it
keeps, what it answers) checked by an end-to-end test through the socket, and every fact about a car is looked for
from the most authoritative source down, so that no dealer page or one model call can decide what exists.

---

## A. Why

Chat 725e7437, one session, five separate failures, none caught by a test:

1. "Not this car → 320 d" stored the model "320 d" and dropped the year (the card button split words by code; its
   only test used "SEAT Arona").
2. The versions list of the BMW 3 Series was the `versions` reader's rows of **one dealer page**; the live call lost
   the 320d row (7 of 7 re-runs keep it), the list was cached for 60 days and taken as proof: "BMW 320 d has no
   version 320d", then "could not settle — remove it?".
3. The EU registry (EEA) answered 502 and the empty answer was cached for a day.
4. On the replay (2026-11-28, chat 6e032fe4) the old interpreter, which still decides, returned **no cars** for the
   first message; the cars came from the word safety net without years or models. The shadow understander (013 S3)
   read both cars right (C-Class 2026, BMW 2 Series 220d 2024).
5. "320d" said twice stayed a trim word: the ladder asked "318d or 320d?" again.

1–3 are fixed (PR #163). 4–5 and the class of failure behind all five are this spec.

## B. Evidence (verified 2026-11-28)

Paths under `backend/src/automind/` unless stated. Full inventories: `audit-interactions.md`, `audit-sources.md`.

| # | Fact | Where |
|---|---|---|
| B1 | 13 socket message types, 5 presets, 5 confirmation kinds, 1 PATCH. Only rating / bad source / challenge are tested through the socket (`ChatSocket`); every other "e2e" test calls the runner and skips `ws.py`, whose `_resume_payload` and `_car_edit_preset` have no test | `delivery/web/ws.py:67-91,252,269`; `tests/graph/test_feedback.py` |
| B2 | Car "Change": only `engine` has a full-turn test; generation, trim, gearbox, remove, not_this_car none | `tests/graph/test_car_edit.py` |
| B3 | Untested answers: chip with `option_id` in a full turn (and `runner.py:72` drops `option_id` while a question is open); variants `option:` and skip; cost "run"; card "not now"; intake `edit_field` except engine; weights slider and reset; "find it" on the verdict card sends free text | audit §Gaps 2–6 |
| B4 | What an action must keep is written for 3 actions only (010 FR-035–FR-039, 013 T012/T013, 007 FR-014); 007's contract says PATCH during a turn is 409, the code queues it | `specs/007-profile-assessment/contracts/case-patch-and-rescore.md:38`; `delivery/web/rest.py:236-240` |
| B5 | Identification has no source tier: URLs are ranked by `_rank` (make as a host substring = +3, so dealers rank as the maker; km77 +2), then `_richest` re-sorts the pages read by the count of CV figures only — a dealer stock table wins | `acquisition/identity_readers/web.py:141-195` |
| B6 | Any page with ≥ 3 versions becomes the list, cached 60 days, regardless of its kind | `chat/application/services/identification/versions.py` `_from_docs` |
| B7 | `AUTHORITY` (MANUFACTURER > INSTRUMENTED_TEST > PUBLICATION > ENCYCLOPEDIA > SPEC_DATABASE) exists but is used only in research ranking and value selection, never in identification; no DEALER / CLASSIFIED / REGISTRY type | `shared/evidence/sources.py:13,89-103`; `acquisition/pipeline/locate.py:144` |
| B8 | Datasets: only EEA CO2 is wired for identification, live query of the make, run **last** and only for combustion cars, never cached as a list; RDW loaders exist but are not used there | `identity_readers/infrastructure/wiring.py`; `versions.py` lookup |
| B9 | Maker sites: plain HTTP + trafilatura, no JS; bmw.es data pages fetch ERROR on every try since 2026-11-27; line-up reads the maker's home page only | `acquisition/infrastructure/pages.py`; `page_snapshots` |
| B10 | `model_versions` is always written as market ES, even for versions found abroad | `chat/infrastructure/persistence/repositories.py:602` |
| B11 | The `versions` reader's output is not stored; dropped versions were not logged until PR #163 | `identity_readers/web.py:99` |
| B12 | External catalogues checked on their own pages (`audit-sources.md` §External): VehiclesDB (CC-BY-4.0) and @meterapp/vehicle-db are make/model only, no versions; carscatalogue has no data and no license; vPIC is US only; Wikidata misses generations (no G20). Version-level open data: EEA CO2 (EU, kW/cc/fuel/commercial name/type-variant-version, per country, yearly), DGT MATRABA (Spain, monthly, version + kW), RDW (NL, CC0, daily, list price). Commercial: JATO (trial), Eurotax/Autovista, auto-data.net API | `audit-sources.md` |

## C. Goals

1. **A contract per interaction**: one table (§D1) says, for each thing the person can do, what it changes, what it
   must keep, what the agent answers, and the failure answer. The table is code (`chat/domain/interactions.py`), not
   prose; a checker fails when a socket message type, preset, confirmation kind or Change field has no row.
2. **A test per row through the socket**: each row has a scenario test that sends the real client message to
   `ChatSocket` and asserts the contract on the case and the answer (no LLM: fake reader; one live replay suite
   nightly).
3. **The person's words are the truth for identity**: anything named (make, model line, engine code, year,
   condition, mileage) is kept until the person changes it; a button never loses what it does not edit.
4. **Never "it does not exist" from one source**: the agent says "I did not find" unless a tier-1 source (§D2) lists
   the model's range and lacks the version; before that it searches the named thing on its own (done for versions in
   PR #163, generalised here).
5. **Sources top-down**: identification and research read tier 1 (registries, the maker, our verified catalogue)
   before tier 2 (spec databases, major editorial) and tier 3 (dealers, classifieds, small-market sites) — tier 3 may
   add details (price, stock, trim names) but never define what a model range is.
6. **Every decision about a source is traceable**: which tier answered, what was read, what was dropped and why
   (`turn show` extended).

## D. Design

### D1. Interaction contracts

`chat/domain/interactions.py`: `Interaction` (StrEnum, one member per row below), `Contract` (frozen: `sent_as`,
`changes: frozenset[CaseField]`, `keeps: frozenset[CaseField]`, `answers: AnswerKind`, `on_failure: AnswerKind`,
`while_question_open: Entry`), `CONTRACTS: Final[Mapping[Interaction, Contract]]`. A property test runs every
interaction on generated cases and checks `keeps` (the fields not in `changes` are equal before and after), the
answer kind and that the turn ends in a stable status.

| Interaction | Changes | Must keep | Answer |
|---|---|---|---|
| Typed message | what the understanding names (013) | every car fact not named in it | answer + re-ask (013 G9) |
| Chip (`option_id`) | the one level the option sets | other levels, other cars, typed words | next question or the card |
| "Choose for me" | the open level(s), origin CHOSEN | levels the person stated | next question or the card |
| Card yes / not now | confirmation / `declined_plan` | cars, versions | research cost or report / ack |
| Card field edit | that field, then identify again | other fields, other cars | the card again |
| Variants: confirm / option / remove / skip | resolution, variant / car removed | other cars, stated levels | card or report |
| Cost run / skip | `cost_approved` / declined plan | case | research / answer from data |
| Feasibility choices | budget intent, condition | other cars | verdict, then report |
| Limit continue / stop | budget extension / stop | data found so far | research / answer from data |
| Change: generation / engine / gearbox / trim | that hint; lower levels re-asked | make, model, year, condition, mileage, other hints above | the car's next step |
| Change: not this car | the car's identity (read like typed text) | year, condition, mileage unless stated; rejections | the car's next step |
| Change: remove | the car | other cars, profile | report or next question |
| Find it (panel, verdict, suggestions) | research of named cars × areas | case | report update |
| Panel PATCH (persona, profile, budget, weights, reset) | those fields, `basis=STATED` | cars, versions, data | rescore, no search |
| Stop / cancel | turn cancelled | validated data | ack |
| Rating / bad source / challenge | feedback, truth signal / claim | case | ack / corrected value |
| Reconnect (`hello`) | nothing | everything | open question re-sent |

Fixes the table forces (each a test first): chip `option_id` kept while a question is open (`runner.py:72`);
"find it" on the verdict card sends `find`; the frontend sends `language`; 007 contract updated to "queued";
"320d" (an engine code in trim words) is the engine family (`wanted()` reads codes from `trim_hint`); the `rephrase`
templates ("There is no such engine") say "not found" (§C4).

### D2. The source pyramid

Tiers, one field on every source (`config/sources.yaml tiers:`; `evidence.tier_of(url) -> Tier`):

| Tier | What | Used for | Examples (to confirm per market) |
|---|---|---|---|
| 0 | Our verified catalogue and caches built from tier 1 | first, always | `vehicle_variants` CONFIRMED, `model_versions` with a tier-1 source |
| 1 | Official registers and makers | the range: what exists, years, kW/cc/fuel | EEA CO2 (EU, bulk yearly CSV, not live SQL), DGT MATRABA (ES monthly), RDW (NL, CC0), maker's configurator / price list / press site |
| 2 | Spec databases and major editorial | engines, gearboxes, drives, missing years | km77, ultimatespecs, auto-data, coches.net/autopista fichas, Wikipedia (aliases) |
| 3 | Dealers, classifieds, small-market sites | prices, stock, trim names, used offers | caetano.es, bmwpremiumselection.es, coches.net listings |

Rules (code, `identity_readers` + `research_order`):

- R1 Searches go tier by tier: tier 1 `site:` / dataset queries first, open searches after; a tier is skipped when
  the level is already settled by a higher one.
- R2 A versions list needs one tier-1 source, or two independent tier-2 sources that agree on ≥ 80 % of the
  versions; a tier-3 page can only **add** versions (marked LESS_CERTAIN) to a list, never form one.
- R3 "Not found" is said only after a named search (PR #163); "does not exist" only when a tier-1 list of that
  generation lacks it.
- R4 Dealers never get the maker's bonus: "official" is `evidence.is_official` only (no make-in-host rule).
- R5 Datasets first, not last: EEA (and DGT for Spain) bulk-loaded monthly into the gold store, read offline; the
  live SQL stays a fallback with a 1-hour failure cache.
- R6 Maker sites that need JS or refuse: a per-make entry (`config/makes.yaml official_data`: price list PDF, press
  site, configurator API if its terms allow) — owner decides each (autonomy boundary: robots/terms stay human).
- R7 Every source read in identification is recorded with its tier and what it gave (`identity_reads`, 90 days) and
  shown by `turn show`.

External catalogues (B12): VehiclesDB as the make/model id and alias skeleton (CC-BY-4.0, attribution in the about
page); no commercial source without the owner's decision (§H).

### D3. Tests

- `tests/e2e/socket/` — a fixture opens `ChatSocket` on a test app with a fake reader and fake search; one module per
  interaction group; every `CONTRACTS` row has ≥ 1 scenario; a checker fails on a row without one.
- Regression suite of the owner's failed chats (725e7437, d170b861, 4bb83866, eb81dd90) as socket scenarios with
  recorded reader answers.
- Nightly live replay of the same chats (≈ €0.3) beside the understanding eval; failures go to the misses report.
- Sources: golden pages (caetano.es, km77 320d, bmw.es) with the reader answer recorded; tests for R1–R4.

## E. Acceptance

- Every row of `CONTRACTS` has a passing socket test; the checker fails when a new message type or field has none.
- The five failures of §A replayed: identified without a question the person already answered; no "does not exist"
  from tier 2/3 sources.
- On 20 models of the eval set, the versions list has a tier-1 or two-tier-2 source in ≥ 90 %; no list formed by a
  dealer page alone.
- `turn show` lists the sources read with their tiers.

## F. Steps (one PR each)

- IC1 `CONTRACTS` table + checker + socket test harness; tests for the rows that pass today; failing rows strict
  xfail with the step that fixes them.
- IC2 The fixes D1 lists (chip id while a question is open, verdict "find it", language, engine codes in trim words,
  "not found" wording everywhere, 007 contract text); xfails removed.
- SP1 Tiers: `tier_of`, `sources.yaml tiers`, R4, R2 in `_from_docs` / `_richest` (tier first); dealer list rows
  downgraded; existing `model_versions` rows re-checked (audit CLI, owner's yes before deleting).
- SP2 Datasets first: EEA bulk load (+ DGT for Spain if §H agrees), offline read before web search, cached as a tier-1
  list for combustion cars.
- SP3 `identity_reads` record + `turn show`; R1 order in research (`search_plan` rounds by tier).
- SP4 Maker data entries per make (R6), the owner approves each source.
- 013 S4 (switch to the understander) is not in this spec but is the largest single fix for §A.4 — see §H1.

## H. Owner's decisions needed

1. **013 S4 now?** The replay shows the old interpreter losing both cars; the shadow understander read them right.
   Proposal: S4 next, with gemini-3.6-flash as the understander (goals 93 %, p95 3.3 s), before IC2.
2. **Order**: IC1 → S4 → IC2 → SP1 → SP2 → SP3 → SP4 (proposal); 015 PL5 after IC2.
3. **DGT MATRABA** (Spanish registrations, monthly, version + kW) as a tier-1 source: terms are the Spanish public
   reuse notice (attribution) — yes / no?
4. **VehiclesDB** as the make/model skeleton (CC-BY-4.0, attribution "Vehicle data by VehiclesDB") — yes / no?
5. **Commercial data** (JATO trial, Eurotax): look now, later, or never?
6. **Tier-3 lists**: delete the cached `model_versions` lists whose only source is a dealer (audit first, backup) —
   yes / no?
