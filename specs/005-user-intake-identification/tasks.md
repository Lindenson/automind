---
description: "Task list for 005 — Understanding the user: intake and identification"
---

# Tasks: Understanding the User — Intake and Identification

**Input**: Design documents from `/specs/005-user-intake-identification/`

**Prerequisites**: plan.md, spec.md, research.md (R0–R14), data-model.md, contracts/intake-protocol.md, quickstart.md

**Tests**: REQUIRED.
- Constitution IX requires a test-first core.
- The incident chat 5be54966 is the first regression test.
- The tests and the golden dialogues G21–G30 are written before the code they cover.

**Organization**: tasks are grouped by user story.
- US1 (every reply moves forward), US2 (open-world brands) and US3 (corrections) are P1 and together form the MVP.
- US1 comes first because it holds the identify step that US2 and US3 plug into.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1–US6 from spec.md
- Paths are relative to the repository root (`backend/`, `frontend/`)

---

## Phase 1: Setup (configuration, migration)

**Purpose**: the files every later phase reads.

- [X] T001 [P] Create `backend/config/makes.yaml` (research R2, R3).
  - About 60 makes sold in Spain, each `{canonical: {aliases: [..], translit: [..], es_site: "<domain/path>", group: <parent>|null}}`.
  - Include European, Japanese, Korean and US makes, plus Chinese: BYD, MG, Omoda, Jaecoo, Chery, EBRO (group Chery), Leapmotor, Xpeng, Lynk & Co, Zeekr, DFSK, Polestar, Cupra, Dacia, SEAT, Škoda.
  - Russian transliterations, e.g. сеат, атека→(model alias in aliases.yaml), биад/бид/бyd, хендай/хюндай/хундай, киа, шкода, тойота, мазда, хонда.
- [X] T002 [P] Create `backend/config/regions.yaml` (research R11).
  - The 17 autonomous communities and 50 provinces, each `{code: {names: [es, ru, en variants], climate: HOT|MILD|COLD|MOUNTAIN}}`.
  - Andalucía, Murcia, Valencia interior and Extremadura → HOT; Cantabria, Asturias and Galicia → MILD; Castilla y León interior → COLD.
  - Add generic phrases: "юг Испании" / "sur de España" / "south of Spain" → HOT, "север" → MILD.
- [X] T003 [P] Rewrite `backend/config/questions.yaml` as v2 (research R9).
  - Every kind is `{en, ru, es, rephrase: {en, ru, es}}`.
  - Add the kinds CONDITION (one question for all cars), ENGINE, MAKE_LINEUP ("Which <make> model: …?") and PROPOSE ("I'll take <car> — OK?").
  - Remove every literal option fallback ("make and model", "year or generation").
  - Placeholders: `{car}`, `{options}`, `{count}`, `{make}`.
- [X] T004 [P] Add the `lineup` role (a web reader, no tools; cheap Gemini model with the existing fallback) to `backend/config/models.yaml`. Add an `intake:` section to `backend/config/search.yaml` with `max_attempts_per_item: 2`, `max_attempts_per_car: 4`, `lineup_ttl_days: 30` and `lineup_max_pages: 2`.
- [X] T005 Write migration `backend/alembic/versions/0008_intake.py` (data-model.md).
  - `vehicle_variants` gains `engine_cc int null` (600–8000), `power_kw int null` (30–750) and `fuel varchar(8) null` (`petrol|diesel|hybrid|mhev|phev|bev|lpg`).
  - New table `brand_lineups`: id varchar(36) PK, make varchar(80), market varchar(2) default 'ES', models jsonb, sources jsonb, fetched_at timestamptz; unique (make, market).
  - New table `intake_events`: id varchar(36) PK, chat_id varchar(36) FK chats ON DELETE CASCADE, turn_id varchar(36), car_key varchar(16) null, kind varchar(20), item varchar(16) null, details jsonb, created_at timestamptz; index on chat_id.
- [X] T006 Add the ORM models `BrandLineup` and `IntakeEvent` and the Variant columns to `backend/src/automind/infrastructure/db/models.py`. Add `IntakeEvent` to the chat-scoped deletion list in `backend/src/automind/infrastructure/db/repositories.py`. Apply 0008 to the Docker DB after `scripts/backup` (pg_dump to `backups/pre-005-*.dump`).
- [X] T007 Write `backend/scripts/backfill_engine.py` (run by `scripts/repair-data.sh --engine`). It fills `engine_cc`, `power_kw` and `fuel` of existing variants from `variant_name` with `identity.parse_engine` (T010), leaves unparsed rows null and prints counts.

---

## Phase 2: Foundational (pure parsers, case model, registry)

**Purpose**: pure building blocks every story uses. ⚠️ No story work before this phase is green.

### Tests first

- [X] T008 [P] Write `backend/tests/unit/test_engine_parse.py` (research R4). It covers:
  - "1.5" / "1,5" / "1500" → 1.5 L;
  - "1.5 TSI 150 CV" → 1.5, 150 hp, 110 kW, family TSI, petrol;
  - "2.0 TDI 110 kW" → diesel;
  - "150 л.с.";
  - "DM-i" → phev;
  - "eléctrico" / "электро" → bev;
  - "дизель" → diesel;
  - "Seat 1.5 двигатель" → 1.5;
  - negation: the negated value is dropped and the other one is kept. "not 1.0 but 1.5" → 1.5; "1.5, а не 1.0" → 1.5; "не 1.0, а 1.5" → 1.5;
  - years (2025) and km (60 000 km) are never read as an engine.
- [X] T009 [P] Write `backend/tests/unit/test_transliteration.py` and `backend/tests/unit/test_makes.py` (research R3).
  - "сеат атека" → SEAT / Ateca; "хендай туссан" → Hyundai / Tucson; "биад сил ю" → BYD / Seal U; "шкода карок" → Škoda / Karoq.
  - The make registry matches aliases, transliterations and fuzzy names (WRatio ≥ 85), and returns None for "Build Your Dream" unless it is an alias of BYD (add it).
  - A domain match: "https://www.byd.com/" → BYD.
- [X] T010 [P] Write `backend/tests/unit/test_intake.py` (research R5, R6, R11).
  - `identity_key` changes when the engine, gearbox, year, condition or trim changes.
  - `parse_distance`: "1-2 тыс км в месяц" → (12000, 24000); "20k a year" → (20000, 20000); "2 000 km al mes" → (24000, 24000).
  - `next_step` never returns a question whose hash equals the last one; it returns PROPOSE after 2 attempts on one item and REMOVE_OR_CHOOSE after 4 on one car.
  - `progress` is true when a fact changed or the outcome improved (NOT_FOUND → CHOICES → IDENTIFIED).
- [X] T011 [P] Write `backend/tests/unit/test_questions_i18n.py`. Every kind in questions.yaml has en, ru and es plus rephrase variants. Formatting with empty options never yields "make and model" or an English word in a ru/es text (a stop-list of English words).

### Implementation

- [X] T012 [P] Implement `parse_engine(text) -> EngineHint | None`, `engine_fits(hint, engine_cc, power_kw, fuel) -> bool` (±0.05 L, ±3 kW, equal fuel) and `transliterate_ru(text) -> str` in `backend/src/automind/domain/identity.py`. Make T008 and the transliteration part of T009 pass.
- [X] T013 Extend `backend/src/automind/domain/casefile.py`.
  - `EngineHint` (fields and ranges as in data-model.md: displacement_l 0.6–8.0, power_hp 40–1000, power_kw 30–750, fuel enum, family ≤ 16 chars, evidence ≤ 120 chars) as `Constraints.engine_hint`.
  - `CaseCar.previous_label`, `CaseCar.identify` (outcome, need, choices, checked, at) and the computed `display_name`.
  - `Intake` (attempts, last_questions ≤ 6, proposed, card, card_confirmed) as `CaseFile.intake`.
  - `Profile.region` (≤ 60 chars), `region_code`, `climate`, `annual_km_min` / `annual_km_max` (1,000–200,000, min ≤ max).
  - The `CONFIRM_INTAKE` pending kind.
  - The QuestionKinds CONDITION, ENGINE, MAKE_LINEUP and PROPOSE.
  - Old case JSON must still load (defaults everywhere).
- [X] T014 Implement `backend/src/automind/domain/intake.py`: `identity_key(car)`, `progress(before, after, outcome_before, outcome_after)`, `next_step(case, outcomes, limits) -> Step` (ASK items ≤ 3, PROPOSE, REMOVE_OR_CHOOSE, CARD, NONE), `question_hash(car_key, item, text)`, `record_asked(case, items)` and `parse_distance(text) -> (min, max) | None`. Make T010 pass.
- [X] T015 [P] Implement `backend/src/automind/application/makes.py`: load `makes.yaml` into `Reference.makes`, `match_make(text) -> str | None` (alias, translit, fuzzy, URL domain) and `make_site(make) -> str | None`. Wire it into `backend/src/automind/infrastructure/config.py`. Make the rest of T009 pass.
- [X] T016 [P] Implement localized templates in `backend/src/automind/application/ask.py`: `template(kind, lang, rephrase=False)`. Options are always concrete; a question without options has no options clause. Make T011 pass.

**Checkpoint**: `scripts/check.sh` is green; old cases load; no behaviour change yet.

---

## Phase 3: User Story 1 — Every reply moves the identification forward (P1) 🎯 MVP

**Goal**: every reply is applied, each car is identified again in the same turn, no question is repeated, and after 2 attempts the assistant proposes a concrete car.

**Independent test**: replay the incident with a fake line-up for BYD. "BYD Seal U" identifies the car, no question repeats, and research waits for the confirmation.

### Tests first

- [ ] T017 [P] [US1] Write golden `backend/tests/golden/g21_byd_seal_u_vs_ateca.yaml` (the incident, Russian, the 6 user messages verbatim) with cassettes for the fake search, line-up and resolver. Assertions:
  - no identical question twice;
  - BYD Seal U identified by the 2nd user reply;
  - no `general` reply;
  - the Ateca engine is 1.5 TSI on the card;
  - all text in Russian.
  Extend `backend/tests/golden/schema.py` and `runner.py` with the assertions `no_repeated_question`, `identified_within`, `no_role: general`, `language` and `card_field`.
- [ ] T018 [P] [US1] Write `backend/tests/graph/test_identify_loop.py`:
  - the same make and model repeated after UNKNOWN triggers a new lookup (not "not understood");
  - after 2 failed attempts the reply is a PROPOSE with a yes/no;
  - after 4, remove or "choose for me" is offered;
  - the question text after a repeat uses the rephrase template.

### Implementation

- [ ] T019 [US1] Implement `backend/src/automind/application/identify.py`: `identify_car(ports, car, case, year) -> Outcome`. The pipeline:
  1. make registry;
  2. catalog (`resolve.assess_car`);
  3. line-up (US2 hook, a no-op until T029);
  4. resolver (`resolve.resolve_with_llm`);
  5. engine match.
  It returns IDENTIFIED (one variant), CHOICES (2–6 Choice items), NEED (item) or NOT_FOUND (with `checked` URLs). It does not raise UnknownModel to the node.
- [ ] T020 [US1] Add `backend/src/automind/orchestration/nodes/identify.py`. It runs `identify_car` for every car that is not settled or whose `identity_key` changed, stores `car.identify`, sets `variant_id` / `label` / `resolution` (AUTO_OK only for a single catalog fit of a NEW car with nothing missing) and records `intake_events`. Wire `apply_delta → identify → assess` in `backend/src/automind/orchestration/graph.py`.
- [ ] T021 [US1] Replace `_not_understood` / `_pending_answered(keep=)` in `backend/src/automind/orchestration/nodes/understand.py` with `intake.progress`. A reply without progress increments `intake.attempts[car][item]`. The pending question is replaced by the next step every turn (never kept verbatim).
- [ ] T022 [US1] Change policy rule 2 in `backend/src/automind/domain/policy.py` to use `intake.next_step` (ASK / PROPOSE / REMOVE_OR_CHOOSE). Remove the sticky `UNKNOWN_MODEL` question and the `REASK` set from `backend/src/automind/domain/identification.py`; `settled()` uses `car.identify.outcome`. Update `backend/tests/unit/test_identification.py` and `test_policy*.py` accordingly.
- [ ] T023 [US1] Rewrite `ask_node` in `backend/src/automind/orchestration/nodes/confirm.py` to build questions from `intake.next_step`:
  - localized templates (T016) with `display_name` instead of `request_text`;
  - concrete options from `car.identify.choices` as `quick_replies` (never empty; `suggested` flag);
  - the PROPOSE text with yes/no chips;
  - store the question hashes.
  The asker model only writes the one-line acknowledgement (prompt `backend/src/automind/orchestration/prompts/asker.md` v2).
- [ ] T024 [US1] Treat a reply that restates the whole request as both an answer and a correction (FR-005). In `backend/src/automind/orchestration/prompts/interpreter.md` v2: while PENDING exists, cars named again map to their existing keys via `set_car_context` (never `add_cars` duplicates). Add example 7, from the incident: "ну дак сравни byd seal u с сеатом атека 1.5 двигателя" → set_car_context car#1 {make BYD, model Seal U}, car#2 {engine_hint 1.5}.

**Checkpoint**: G21 passes up to the card (the card itself is US5: until then CONFIRM_VARIANTS is shown); T018 is green.

---

## Phase 4: User Story 2 — Open-world brands and models (P1)

**Goal**: makes and models absent from the catalog are found on the web with sources and offered as concrete choices. "Find the matching model" proposes 1–3 models with reasons.

**Independent test**: "BYD vs SEAT Ateca for a family" offers real BYD models on sale in Spain. "Choose for me" recommends one, with a reason.

### Tests first

- [ ] T025 [P] [US2] Write `backend/tests/unit/test_rank_lineup.py` (research R12):
  - FAMILY + 18,000 km + priorities efficiency/ownership_cost over a fake BYD line-up (Dolphin hatch BEV, Atto 3 SUV BEV, Seal U SUV PHEV, Seal sedan BEV, Sealion 7 SUV BEV) → SUVs first, PHEV/BEV ranked by km;
  - a price band near the other car (Ateca €30k ± 30%);
  - machine reasons;
  - deterministic order.
- [ ] T026 [P] [US2] Write `backend/tests/integration/test_lineup.py` with a fake search and page store:
  - models not occurring in the document are dropped;
  - a price without its excerpt is dropped;
  - no official or price-list source → not stored;
  - the cache is used inside the TTL and refreshed after it.
- [ ] T027 [P] [US2] Write goldens `g22_unknown_brand_mg.yaml` ("MG ZS или Dacia Duster"), `g25_transliteration.yaml` ("хендай туссан или киа спортейдж"), `g26_find_model_for_me.yaml` ("подбери Omoda или Jaecoo для семьи") and `g24_url_answer.yaml` (a model page is read and "from the page I took: …" is shown; a coches.net link is refused, with the reason) in `backend/tests/golden/`.

### Implementation

- [ ] T028 [US2] Write prompt `backend/src/automind/orchestration/prompts/lineup.md` v1 (a web reader: `<untrusted_document>`, no tools). It returns `[{model, body, powertrains[], price_from_eur|null, excerpt}]` for the Spanish market only, and never adds a model that is not in the documents.
- [ ] T029 [US2] Implement `backend/src/automind/application/lineup.py`: `get_lineup(ports, make) -> Lineup | None`.
  - Cache-first `brand_lineups` (TTL from config).
  - Search ES `"<make> gama modelos precios España"` plus the official `es_site`, reading ≤ 2 pages through the page store (robots, deny-list).
  - The `lineup` role extracts; each model is checked with `evidence.occurs` and each price must be in its excerpt.
  - Stored only with ≥ 1 official or price-list source.
  Plug it into step 3 of `identify_car` (T019).
- [ ] T030 [US2] Change `_check_known` in `backend/src/automind/application/resolve.py`. A model in the make's line-up is known without the resolver returning a generation; for a NEW car the generation is "current" and its label notes the line-up source. "Unknown" is returned only after the line-up lookup ran, and it comes with the closest line-up names (fuzzy). An empty list never reaches a question.
- [ ] T031 [US2] Implement `rank_lineup(lineup, profile, other_cars, budget) -> list[Choice]` in `backend/src/automind/domain/intake.py` (top 1–3, machine reasons, `suggested=True`). Use it in `identify_car` when the make is known and the model is missing, or when the request is "find the matching model" / choose_for_me. Make T025 pass.
- [ ] T032 [US2] Classify a URL in a reply in `backend/src/automind/application/identify.py` (research R10):
  - deny-listed → refused, with the reason in the user's language;
  - a maker home page (domain in makes.yaml) → sets the make and shows the line-up;
  - a model page → read via the page store and resolved; the reply carries "from the page I took: …" (phrase in `backend/src/automind/orchestration/phrases.py`, en/ru/es).
- [ ] T033 [US2] Pass the line-up documents to the resolver in `_resolver_docs` in `backend/src/automind/application/resolve.py` (when known), and add the Spanish km77 / official-site query for a make without a catalog entry. The resolver prompt `backend/src/automind/orchestration/prompts/resolver.md` v4: prefer the versions listed in the line-up; return engine_cc, power_kw and fuel.

**Checkpoint**: G22, G24, G25 and G26 pass; G21 identifies BYD from the line-up.

---

## Phase 5: User Story 3 — Corrections change the car (P1)

**Goal**: a correction of any part of the identity re-identifies the car (even if it was resolved or confirmed) and is shown as "before → after".

**Independent test**: resolve "SEAT Ateca", say "1.5, not 1.0". The car becomes a 1.5 TSI version and the change is shown; no research runs on the 1.0.

### Tests first

- [ ] T034 [P] [US3] Write `backend/tests/graph/test_corrections.py`:
  - an AUTO_OK Ateca 1.0 plus "1.5 двигатель" → variant cleared, a 1.5 version selected, notice "SEAT Ateca 1.0 TSI 110 CV → 1.5 TSI 150 CV …";
  - "Ateca 2.5 diesel" → "no such version", with the engines that exist;
  - "automatic", "2025" and "it is used, 60,000 km" each re-identify;
  - a correction during research → jobs of the old variant are ignored, and the new identity needs confirmation;
  - research results of the old variant are not shown for the new one.
- [ ] T035 [P] [US3] Write golden `backend/tests/golden/g23_engine_correction.yaml` ("Seat Ateca vs Skoda Karoq" → "Ateca 1.5, not 1.0" → card shows 1.0 → 1.5).

### Implementation

- [ ] T036 [US3] In `apply_delta_node` (`backend/src/automind/orchestration/nodes/understand.py`), compare `intake.identity_key` before and after for every car. On a change:
  - clear `variant_id` / `label` / `resolution`;
  - set `previous_label`;
  - reset `intake.card_confirmed`;
  - rebuild `display_name`;
  - record a CORRECTED intake event.
- [ ] T037 [US3] Merge the deterministic `parse_engine` result into the interpretation in `backend/src/automind/application/interpret.py`: a parser field fills an empty interpreter field, and on a conflict the parser wins and the conflict is logged. Interpreter prompt v2: the engine goes to `constraints.engine_hint`, never to trim_hint; add an Ateca 1.5 example.
- [ ] T038 [US3] Use the engine in `_fits` and `_rank` (`engine_fits`) and store `engine_cc` / `power_kw` / `fuel` in `upsert_variant` in `backend/src/automind/application/resolve.py`. Pass `engine_hint` to the resolver context (`_context`). A correction matching no version → NEED(ENGINE) with the existing engines as options (FR-015).
- [ ] T039 [US3] Add the "before → after" notice phrase (en/ru/es) in `backend/src/automind/orchestration/phrases.py`, emitted by the identify node when `previous_label` is set and a new label is chosen. Ignore results of jobs whose `variant_id` no longer belongs to the case in `collect_round` (`backend/src/automind/orchestration/nodes/research.py`).

**Checkpoint**: MVP (US1–US3) is complete. G21–G26 pass in replay. Deploy to dev and Docker. Manual check of the incident message (paid calls: announce the estimate first).

---

## Phase 6: User Story 4 — Full intake: car facts and the person (P2)

**Goal**: new/used, year, region and climate, km range and the profile are inferred with evidence or asked (≤ 3 grouped questions).

**Independent test**: the incident's first message yields:
- family; city + motorway;
- 12,000–24,000 km/year;
- south of Spain (HOT);
- priorities;
- exactly one question, new or used, for both cars.

### Tests first

- [ ] T040 [P] [US4] Write `backend/tests/unit/test_profile_intake.py`:
  - region phrases → region_code and climate;
  - km range → annual_km middle;
  - CONDITION inferred from "new" / "0 km" / "replace my old" / a mileage / a past year;
  - one CONDITION question for all UNKNOWN cars;
  - at most 3 questions, grouped.
- [ ] T041 [P] [US4] Write goldens `g27_used_with_mileage.yaml` ("б/у Tucson 2019, 80 тыс км, или новый Sportage") and `g29_region_climate.yaml` ("Севилья, 2000 км в месяц, PHEV или дизель?") in `backend/tests/golden/`.

### Implementation

- [ ] T042 [US4] Apply region and km in `backend/src/automind/domain/casefile.py` `apply`: `set_profile.region` → region_code and climate via `regions.yaml` (`Reference.regions`, loaded in `backend/src/automind/infrastructure/config.py`); `set_annual_km_range` → min / max / middle, with evidence.
- [ ] T043 [US4] Interpreter prompt v2 (`backend/src/automind/orchestration/prompts/interpreter.md`):
  - region with verbatim evidence;
  - km range ("1-2 тыс в месяц") → `set_annual_km_range`;
  - new or used per car from words;
  - the deterministic `parse_distance` fallback merged in `backend/src/automind/application/interpret.py`.
- [ ] T044 [US4] CONDITION and YEAR steps in `intake.next_step` (`backend/src/automind/domain/intake.py`):
  - one CONDITION question for all cars with condition UNKNOWN;
  - a NEW car's year is "current" (ASSUMED);
  - a USED car asks YEAR and MILEAGE together;
  - profile questions (KM_PER_YEAR, FAMILY_SIZE) stay non-blocking, as in 004.
- [ ] T045 [US4] Show region / climate and the km range in the case panel (`frontend/src/components/CasePanel.tsx` AboutYou) and in the i18n dictionaries `frontend/src/i18n/{en,ru,es}.ts`. Use the km range in `backend/src/automind/orchestration/nodes/compute.py` for the TCO label ("at 18,000 km/year (12,000–24,000)").

**Checkpoint**: G27 and G29 pass; the incident's first reply asks one CONDITION question with chips "новый / б/у".

---

## Phase 7: User Story 5 — One confirmation card before research (P2)

**Goal**: one card with cars, profile and cost; every item has a basis; chips edit it; one "yes" starts research.

**Independent test**: after the intake the card lists both cars and the profile. Changing "1.0" to "1.5" on the card updates it with a highlight, and research starts only after "yes".

### Tests first

- [ ] T046 [P] [US5] Write `backend/tests/graph/test_intake_card.py`:
  - all cars IDENTIFIED → CONFIRM_INTAKE with `card` per contracts/intake-protocol.md;
  - every item has a basis, with source for LOOKED_UP and evidence for INFERRED;
  - `intake_edit` engine → card again with `changed: true` and no model call;
  - "yes" → variants CONFIRMED and cost approved below the hard cap → research jobs;
  - above the cap → the card says research stops at the cap;
  - free text on the card → interpreted as a correction;
  - old chats pending on CONFIRM_VARIANTS still work.
- [ ] T047 [P] [US5] Write the vitest `frontend/src/components/IntakeCard.test.tsx`:
  - basis badges;
  - chips send `intake_edit`;
  - changed items highlighted;
  - "yes" sends confirm;
  - texts from i18n ru/es/en;
  - a 375 px layout has no horizontal scroll.
- [ ] T048 [P] [US5] Write golden `backend/tests/golden/g28_ev_vs_phev.yaml` ("BYD Seal U EV или DM-i?" → two different cars on the card, with different fuel).

### Implementation

- [ ] T049 [US5] Implement `backend/src/automind/application/intake_card.py`:
  - `build_card(case, variants, estimate, lang) -> IntakeCard`, with items and basis per data-model.md (sources from the variant evidence and the line-up; evidence from the case);
  - `apply_edit(case, car_key, field, value) -> (case, changes)`, deterministic, with field validation (engine via parse_engine, year 1950–current+1, km 1,000–200,000).
- [ ] T050 [US5] Add `prepare_intake` / `wait_confirm` / `apply_intake` nodes in `backend/src/automind/orchestration/nodes/confirm.py` and policy rule 3 (all IDENTIFIED and not `card_confirmed` → CONFIRM_INTAKE) in `backend/src/automind/domain/policy.py`. A "yes" sets the cars CONFIRMED, `card_confirmed`, and `cost_approved` (if estimate ≤ hard cap). Edges in `backend/src/automind/orchestration/graph.py`. CONFIRM_VARIANTS stays for old pending chats only.
- [ ] T051 [US5] Handle the `intake_edit` client message in `backend/src/automind/api/ws.py`. Resume the waiting turn with `{choice: "edit_field", car_key, field, value}`; `apply_intake` calls `apply_edit` and loops to `prepare_intake`.
- [ ] T052 [US5] Frontend protocol in `frontend/src/lib/protocol.ts`:
  - `ConfirmRequest.card` (Zod, `.catch` for forward compatibility);
  - the `IntakeEditMsg` client message;
  - `quick_replies.items[].suggested` / `reason`.
  Add `editIntake(carKey, field, value)` to `frontend/src/store/chat.ts`. Update `frontend/src/lib/protocol.test.ts`.
- [ ] T053 [US5] Implement `frontend/src/components/IntakeCard.tsx`:
  - per car: rows with value, basis badge (stated / inferred / found / assumed, with the source link or evidence in a tooltip), option chips and changed highlight;
  - a profile section;
  - a cost line;
  - buttons yes / not now;
  - phone layout.
  Route `kind === "intake"` to it from `frontend/src/components/ConfirmCard.tsx`. Add i18n keys in `frontend/src/i18n/{en,ru,es}.ts`. Make T047 pass.

**Checkpoint**: G21 and G23 assert the card; G28 passes; one confirmation instead of two in all new chats.

---

## Phase 8: User Story 6 — Stay on task, speak the user's language (P2)

**Goal**: no generic chat or greeting during the intake, no unnamed models presented as the user's choice, and no English text in ru/es chats.

**Independent test**: replay the incident in Russian. There is no English, no greeting after turn 1, and no model the user did not name unless it is marked as a suggestion.

### Tests first

- [ ] T054 [P] [US6] Write `backend/tests/graph/test_no_general_in_intake.py`:
  - pending QUESTIONS + "BYD это Build Your Dream, китайская компания" → an intake reply (make BYD, its line-up offered), never the `general` role;
  - pending CONFIRM_INTAKE + chitchat → the card again with an acknowledgement;
  - no pending → general as before.
- [ ] T055 [P] [US6] Write golden `backend/tests/golden/g30_brand_explanation.yaml`. Add the assertions `no_greeting_after_first` and `no_unnamed_model_unless_suggested` to all goldens G21–G30 in `backend/tests/golden/runner.py`.

### Implementation

- [ ] T056 [US6] Add policy rule 0 in `backend/src/automind/domain/policy.py`: while `pending.kind in (QUESTIONS, CONFIRM_INTAKE, CONFIRM_VARIANTS)`, a request of `general_question` / `chitchat` is handled as an intake reply. A brand explanation is matched to the make registry (`makes.match_make` on the text, including "Build Your Dream").
- [ ] T057 [US6] Write the general prompt v2 (`backend/src/automind/orchestration/prompts/general.md`): no greeting after the first assistant message (history passed in), never name a model the user did not name unless introduced as a suggestion, and in the conversation language.
- [ ] T058 [US6] Add a language guard in `backend/src/automind/orchestration/nodes/confirm.py` and `report.py`. `phrases.guess_language(output)` ≠ conversation language → regenerate once, then use the template text. Localize the remaining intake notices (GenerationMismatch, variants skipped, unknown) in `backend/src/automind/orchestration/phrases.py`.

**Checkpoint**: G21–G30 pass with the cross-cutting assertions.

---

## Phase 9: Polish & cross-cutting

- [ ] T059 [P] Intake metrics in `backend/src/automind/domain/metrics.py` and the metrics endpoint: replies to confirmed identity (median), repeated questions, corrections changing identity, research on unconfirmed cars (must be 0). Test in `backend/tests/unit/test_metrics.py`.
- [ ] T060 [P] Write ADR-024 "Open-world vehicle identity (make registry plus sourced line-ups)" and ADR-025 "One intake confirmation card" in `docs/adr/`, and update `docs/adr/README.md`.
- [ ] T061 [P] Add a README section "Intake and identification (spec 005)" to `README.md`.
- [ ] T062 Run `scripts/check.sh` (ruff, mypy, import-linter, pytest, vitest, build). Run the engine back-fill (T007) on the Docker DB after a backup. Restart dev (`pkill -x automind-api; scripts/dev.sh`) and `scripts/deploy.sh up`.
- [ ] T063 Run quickstart.md sections 1–3 (replay). Live recording of G21–G30 and the manual incident check (quickstart §4) need paid Gemini and search: announce a cost estimate first and run only after the user agrees.
- [ ] T064 Update the project memory (`automind-project.md`) and close roadmap issue #3 when the live check passes. Mark PR #2 ready for review.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → stories.** T005–T006 (migration) block T007, T029 and T049. T012–T016 block every story.
- **US1 (Phase 3)** comes first: the identify node (T019–T020) is the hook for US2 (T029, T031, T032) and US3 (T036–T039).
- **US2 and US3** can run in parallel after US1 (different files, except `resolve.py`: T030 and T033 (US2) before T038 (US3)).
- **US4** needs US1 (next_step). **US5** needs US1 and US3 (identity, previous_label). **US6** needs US1 (policy) and is otherwise independent.
- **Polish** comes after the stories you ship.

```text
Setup ─► Foundational ─► US1 ─┬─► US2 ─┐
                              ├─► US3 ─┼─► US5 ─┐
                              ├─► US4 ─┘        ├─► Polish
                              └─► US6 ──────────┘
```

## Parallel examples

- Phase 1: T001, T002, T003 and T004 together (separate config files).
- Phase 2 tests: T008, T009, T010 and T011 together. Then T012, T015 and T016 together (T013 → T014 in order).
- US2: T025, T026 and T027 together; then T028 ∥ T031.
- US5: T046, T047 and T048 together; frontend T052 → T053 ∥ backend T049 → T050 → T051.
- Polish: T059, T060 and T061 together.

## Implementation Strategy

1. **MVP = US1 + US2 + US3** (Phases 1–5). This is exactly the incident: the BYD is identified, the Ateca correction works, and no question repeats. Deploy and check the incident message live (with a cost estimate first).
2. **US5 next**: the confirmation card replaces two dialogs with one.
3. **US4 and US6**: complete the intake and the language and on-task guarantees.
4. **Polish**: metrics, ADRs, live goldens.

Every phase ends with `scripts/check.sh` green and a commit. Every story ends with deploy (dev and Docker).
