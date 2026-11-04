# Feature Specification: Reliable Car Identification Ladder and Used Cars Costed as Used

**Feature Branch**: `008-identification-ladder`

**Created**: 2026-11-04

**Status**: Draft

**Input**: User description: "008 — Car identification, rebuilt to be reliable: a deterministic clarification ladder from model to the exact version (year/generation → engine: fuel, displacement, power → gearbox → driven wheels), never loops, never a wrong guess; and used cars costed and scored as used." (full text in the conversation of 2026-11-04; incidents and goals summarised below)

## Context

Identification of the cars to compare has failed the same way in many live chats:

- **Chat 9b5c0b0c (2026-11-04).** The user wrote "Audi A4 2.5 l second hand, 50,000 km" and "new Skoda Octavia 2025 2.0 l", then gave the Audi's year as 2023.
  - The hub offered "A4 B5/B6/B7 2.5 TDI" engines for a 2023 car; these are generations built up to 2008.
  - The option the user picked then conflicted with the year.
  - The car fell into a "remove or choose?" question that no reply could leave. "Choose for me" and "go ahead to the comparison" re-asked it again and again. This was patched in PR #45.
- **The same chat, Skoda.** "2.0 l diesel" was silently taken as the one 2.0 TDI row the catalog happened to hold (115 CV). The 2.0 TDI in Spain comes in 116 CV and 150 CV, and the RS has 200 CV; the power was never asked.
- **The same chat, Audi costs.** The used Audi, with its year unknown, was costed and scored as a new car:
  - no depreciation for its age;
  - no age band for the repair reserve;
  - the purchase-price criterion used the official new price;
  - reliability had no age effect.
- **Earlier chats with the same root cause:**
  - 0d7fd924: invented catalog rows, and a generation stamped on an engine of another generation;
  - 48c8ac65 and 757cff3d: duplicate catalog rows, and hatchback data on an estate (cleaned in PR #44).

**Root causes:**
- Identification guesses from whatever catalog row or resolver answer is at hand.
- There is no sourced list of the versions that actually exist per model generation.
- Levels are mixed: engines from other generations are offered, and a gearbox question offers whole versions.
- Several overlapping question kinds and attempt counters interact, and a state that no answer can leave is reachable.

A draft "version ladder" exists on branch `008-wip-version-ladder`. It is input for the plan, not a decision.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The car is narrowed level by level to the exact version (Priority: P1)

The user names a car in their own words: complete, partial, or wrong. The hub settles it in a fixed order of levels:
1. make;
2. model;
3. the year or generation (for a used car), or the generation on sale (for a new car);
4. the engine: fuel, then displacement and engine family, then power;
5. the gearbox;
6. the driven wheels.

Each level is taken from what the user said when that is unambiguous. Otherwise the hub asks one question with the options that really exist at that level for this car. The hub never fills a level by taking the only catalog row it happens to have.

**Why this priority**: every cost, score and report is computed for the version settled here. A wrong version corrupts everything downstream (constitution II), and this stage is where most live chats went wrong.

**Independent Test**: start chats with the incident phrasings and check:
- the order of the questions;
- the options offered;
- the version finally settled;

against the sourced list of versions of that generation.

**Acceptance Scenarios**:

1. **Given** "new Skoda Octavia 2.0 diesel", **When** the hub identifies it, **Then** it asks which power (116 CV or 150 CV, plus "choose for me"). It does not take a 115 CV catalog row.
2. **Given** "Octavia 2.0 TDI 150 CV", where that engine is sold with one gearbox but with front or all-wheel drive, **When** identified, **Then** the only question asked is front or all-wheel drive.
3. **Given** "used VW Golf 2017 1.5 TSI 150 CV DSG", where everything is unambiguous for that year, **When** identified, **Then** no identity question is asked and the version is shown for confirmation together with the other cars.
4. **Given** an engine option is tapped, **When** the next question comes, **Then** it is about the next level only (gearbox or wheels), never the engine again.

---

### User Story 2 - What does not exist is said, and the question moves one level up (Priority: P1)

When something the user said does not exist at a level for the facts above it, the hub says so plainly. For example: no A4 built in 2023 has a 2.5 engine. The hub then asks the question one level up, offering what does exist. It never offers options that contradict a higher level.

**Why this priority**: in chat 9b5c0b0c, options that could not exist were offered, and the user's pick then blocked the car. This is the direct cause of the loop.

**Independent Test**: give contradictory facts (year against engine, generation against year, fuel against model) and check the message and the options.

**Acceptance Scenarios**:

1. **Given** "used Audi A4, 2023, 2.5 l", **When** identified, **Then** the message says the 2023 A4 has no 2.5 engine and offers the engines of the A4 built in 2023. No engine of B5, B6, B7 or B8 is offered.
2. **Given** the user said "2023" and later picks or types "B5", **When** the newer answer conflicts with the older one, **Then** the newer explicit answer wins. A visible note says what was replaced ("year 2023 → B5 is 1994–2001: which year?"), and the levels below are opened again.
3. **Given** a new car and an engine that is no longer sold, **When** identified, **Then** the message says it is not sold new and offers the engines on sale now.

---

### User Story 3 - The identification never loops (Priority: P1)

Every identity question can be answered in a way that moves on:
- with an offered option;
- with "choose for me" or any equivalent (yes, go ahead, any, whatever, in Russian, Spanish or English);
- by removing the car.

"Choose for me" settles the current level by a documented rule (the most common or base option at that level) and continues down the levels. Each question is asked a bounded number of times. After that, the hub settles the level by the same rule and says so.

**Why this priority**: an endless question is the worst failure for the user. It has happened several times.

**Independent Test**: property tests over the identification states. From every reachable state:
- every offered option and "choose for me" lead to a different state closer to a settled version;
- "remove" leads to the car being removed.

Replay chat 9b5c0b0c and check that it ends with a settled version.

**Acceptance Scenarios**:

1. **Given** any identity question, **When** the user answers "choose for me" / "выбери сам" / "elige tú" / "go ahead" / "да, вперёд к сравнению", **Then** the hub settles that level and the levels below by the rule, without another question about this car, and shows what it chose.
2. **Given** a question has been asked its maximum number of times, **When** the reply again does not answer it, **Then** the hub settles the level by the rule and continues. It never re-asks the same question with the same text.
3. **Given** any identity question, **When** the user says "remove it" / "убери", **Then** the car is removed and the comparison continues with the other cars.

---

### User Story 4 - Used cars are costed and scored as used (Priority: P1)

For a used car, the year (or age) and the mileage are part of what is being compared. Costs and criteria reflect the car's real age and mileage:
- the purchase price is its used market price;
- depreciation starts from its value now;
- repair reserve and large age- and mileage-related costs follow its bands;
- reliability takes age and mileage into account;
- the safety rating is from its era;
- the warranty is either remaining or expired.

If the user does not give the year after one question, the age is assumed from the mileage or the generation and shown as an assumption.

**Why this priority**: in chat 9b5c0b0c, a used Audi was scored as new. Its purchase price, depreciation and repairs were all wrong, so the verdict was meaningless.

**Independent Test**: compare a used car of known year and mileage with a new car. Check each cost line and criterion input for the used car against its age and mileage. Repeat with the year unknown and check the stated assumption.

**Acceptance Scenarios**:

1. **Given** a used car with a year and mileage, **When** scored, **Then** the purchase-price criterion uses the sourced used price for that year and mileage, never the new price. Without a sourced used price, the criterion is marked as having no data.
2. **Given** a used car, **When** ownership costs are computed, **Then**:
   - depreciation starts from the estimated value at its age;
   - the repair reserve uses its age band;
   - documented age and mileage items (timing belt, clutch, DPF …) appear when they are due within the ownership period.
3. **Given** a used car with no year after one question, **When** costs are computed, **Then** an age is assumed from the mileage (or the middle of its generation). A notice says so and invites the user to give the year. The car is never costed with age 0.
4. **Given** a used car, **When** the report is shown, **Then**:
   - figures for the used car are labelled as used: price used, value now, warranty remaining or expired;
   - assumptions are labelled as assumptions.

---

### User Story 5 - The user sees where identification stands and can correct any level (Priority: P2)

While a car is being identified, the user sees its state on one line. For example: "Audi A4 · B9 (2023) · diesel 2.0 TDI · power: ?". At any time they can correct any level ("not 2023 but 2019", "petrol, not diesel"). Correcting a level opens again only that level and the levels below it.

**Why this priority**: transparency prevents silent wrong guesses and lets the user fix the hub's understanding in one message.

**Independent Test**: during identification, correct a higher level and check:
- the lower levels are re-opened;
- the higher levels are kept;
- the status line updates.

**Acceptance Scenarios**:

1. **Given** a car settled as "Octavia 2.0 TDI 150 CV DSG", **When** the user says "it's petrol", **Then** fuel, engine, gearbox and wheels are opened again, while make, model and generation are kept.
2. **Given** a car being identified, **When** a question is shown, **Then** the identification status of that car is shown with it.

---

### User Story 6 - A sourced list of the versions of each model generation (Priority: P2)

For each model generation sold in Spain, the hub keeps a list of its versions:
- engine with power;
- fuel;
- gearboxes;
- driven wheels;
- the years each version was sold.

Each version is backed by the documents it came from. The list is reused across chats while fresh. The final settled version is stored in the catalog from this list, as one row per real version with no duplicates.

**Why this priority**: the ladder of Stories 1–3 is only as good as the list it walks. Without it, the hub can only guess.

**Independent Test**: for a set of models (Octavia, A4, Golf, RAV4, Model 3, Seal U), the list matches the sources for that generation:
- every version's power is written in a document it cites;
- no version from another generation is included.

**Acceptance Scenarios**:

1. **Given** a model generation looked up for the first time, **When** the list is built, **Then** every version keeps its source and excerpt, and a version whose power is not written in its document is dropped.
2. **Given** the same model generation in another chat within the freshness period, **When** identified, **Then** the stored list is reused without a new search.
3. **Given** no source lists the versions, **When** identified, **Then** the hub still follows the levels. It asks the engine as free text (displacement, power or fuel), never offers versions it cannot support, and marks the settled version's identity as less certain.

---

### Edge Cases

- **The user gives a power in another unit or rounding** ("150 hp", "110 kW", "150 л.с.", "116 vs 115 CV"). It is matched to the version within a small tolerance, never to a different power level.
- **A model is a separate line** (Octavia vs Octavia RS, Golf vs Golf GTI/R). The user's words decide the line. The 200 CV RS is offered under "Octavia" only when the user's words allow the RS line.
- **A version exists only in some years of a generation.** It is offered only if the year fits.
- **Electric cars** have no displacement. The engine level is power and battery or range version ("Long Range", "Performance"). The gearbox level is skipped.
- **Plug-in and full hybrids** are separate fuels at the fuel level.
- **The user names a version from another market** (e.g. a US engine). The message says it is not sold in Spain and offers the Spanish versions.
- **Two cars of the same model** in one comparison (e.g. Octavia 116 vs 150). Each car is identified on its own.
- **A previously settled car (chats from before this feature).** It stays settled. It is re-opened only when the user changes a level.
- **The source list contradicts what the user knows about their own car** ("my Octavia has 130 CV"). The user's explicit figure is kept as a stated fact with a visible note. It is never silently replaced.
- **A used car of a model generation with no sourced used price.** The purchase-price criterion is marked as having no data, never filled with the new price.
- **Warranty for a used car.** It is computed from the first registration year and the brand's sourced warranty terms. It is shown as an assumption if the registration year is assumed.

## Requirements *(mandatory)*

### Functional Requirements

**Identification ladder**

- **FR-001**: The system MUST identify each car through ordered levels: make → model → generation (from the year for a used car, the generation on sale for a new car) → engine (fuel → displacement/family → power) → gearbox → driven wheels → settled version. Equipment trim and interior are out of scope.
- **FR-002**: A level MUST be settled from the user's words when they are unambiguous for that level. Otherwise it MUST be asked with the options that exist at that level, given the levels above. A level MUST NOT be settled by taking a single catalog row or a resolver guess that the user's words do not determine.
- **FR-003**: Options at any level MUST be consistent with every settled higher level:
  - year or generation;
  - fuel;
  - displacement;
  - market (Spain);
  - new or used.

  Options that contradict a higher level MUST NOT be offered.
- **FR-004**: When something the user said does not exist for the higher levels, the system MUST say so explicitly, naming the conflicting facts, and MUST ask the nearest level at which a valid choice exists, offering what exists.
- **FR-005**: A newer explicit user answer MUST win over an older one. The system MUST show a note naming what was replaced, and MUST re-open the levels below the changed one, keeping the levels above.
- **FR-006**: When the options at a level are too many to list (more than 6), the system MUST first ask a coarser grouping. Example: engine family and displacement first, then power.
- **FR-007**: Each question MUST concern exactly one level of one car, and its options MUST be options of that level only. A gearbox question MUST NOT offer engines, and an engine question MUST NOT offer generations.

**No loops**

- **FR-008**: Every identity question MUST accept, besides its options:
  - "choose for me" and its equivalents in Russian, Spanish and English (yes, go ahead, any, whatever, "вперёд", "к сравнению", "adelante" …);
  - "remove this car".
- **FR-009**: "Choose for me" MUST settle the current level by a documented rule (the most common or base option of that level, as ordered by the sources), and continue down all remaining levels by the same rule. The choices MUST be shown to the user.
- **FR-010**: Each identity question MUST be asked at most a configurable number of times (default 2) per car and level. After that, the level MUST be settled by the FR-009 rule, with a visible note.
- **FR-011**: Every identification state that the system can reach MUST have at least one reply among the offered ones that moves it to a different state closer to a settled version or a removed car. A state without such a reply is a defect, and the property tests MUST prove that no such state is reachable.
- **FR-012**: The same question text MUST NOT be sent twice in a row for the same car and level.

**Transparency and correction**

- **FR-013**: While any car is not settled, each identity question MUST show that car's identification status on one line: the settled levels and the level being asked.
- **FR-014**: The user MUST be able to correct any level of any car at any time in their own words. Only that level and the levels below MUST be re-opened.
- **FR-015**: Settled cars MUST be confirmed together once, with their full versions, before paid research starts. This follows the existing confirmation card of spec 005.

**Versions of a model generation**

- **FR-016**: The system MUST keep, per model generation sold in Spain, a list of its versions:
  - engine with power (CV and kW);
  - fuel;
  - displacement;
  - gearboxes;
  - driven wheels;
  - years sold.

  Each version MUST be linked to the documents it came from (constitution I).
- **FR-017**: A version MUST be kept only if its power is written in the cited document and its excerpt occurs in the document. Versions of other generations or other markets MUST NOT be kept.
- **FR-018**: The list MUST be reused across chats while fresh. The freshness period MUST be configurable (default 60 days). Looking up a list is part of identification, not research. It MUST stay within the per-turn cost limits and be shown in the turn's usage.
- **FR-019**: The settled version MUST be stored in the catalog from the list, with one row per real version. An existing row of the same version MUST be reused, never duplicated.
- **FR-020**: When no source lists the versions, the system MUST still follow the levels. It MUST ask the engine in free form, MUST NOT offer unsupported options, and MUST mark the settled identity as less certain in the confirmation and the report.

**Used cars as used**

- **FR-021**: For a used car, the year (or age) and the mileage MUST be part of its identity. The year MUST be asked once if not given, together with the identity questions.
- **FR-022**: If the year of a used car is still unknown when costs are computed, the system MUST assume an age:
  - first from the mileage, at a configurable yearly distance;
  - else from the middle of its generation;
  - else a configurable default.

  A notice MUST say so. A used car MUST NEVER be costed or scored with age 0.
- **FR-023**: The purchase-price criterion of a used car MUST use the sourced used market price for its year and mileage. Without one, the criterion MUST be marked as having no data. The new price MUST NOT be used as the purchase price of a used car.
- **FR-024**: Depreciation of a used car MUST start from its estimated value at its age. The repair reserve MUST use its age band. Documented age- and mileage-related costs MUST be included when due within the ownership period.
- **FR-025**: The reliability criterion of a used car MUST include its age and mileage effects. The safety criterion MUST use the rating of its era, and say when the rating period is not comparable with the other cars.
- **FR-026**: The warranty of a used car MUST be shown as remaining (until when) or expired, from its first registration year and the brand's sourced warranty terms. It is an assumption when the year is assumed.
- **FR-027**: The report MUST label which figures of a used car are for the used car (price used, value now, warranty status) and which are assumptions.

### Key Entities *(include if feature involves data)*

- **Identification state (per car)**: the settled value of each level, with its origin (stated, chosen for the user, settled after the maximum number of asks); the level being asked; ask counts per level; notes on replaced answers.
- **Model generation versions**: make, model, generation code and years, market, body; a list of versions (engine label with power, fuel, displacement, gearboxes, drives, years sold), each with source and excerpt; fetched date.
- **Settled version**: the catalog vehicle variant created from one version of the list (one row per real version).
- **Used-car facts**: year or age (stated or assumed, with how), mileage, first registration year, warranty status, used market price (sourced, for the year and mileage).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Replaying chat 9b5c0b0c, chat 0d7fd924 and all golden dialogues settles every car (or removes it on request) in at most 3 identity questions per car, with zero repeated identical questions.
- **SC-002**: "New Skoda Octavia 2.0 diesel" ends with the power the user chose, or the base power after "choose for me", from the versions sold in Spain. It never ends with a power level that is not in the sourced list.
- **SC-003**: "Used Audi A4 2023 2.5 TDI" produces a message saying no such engine exists for that year, and offers only engines of the A4 built in 2023. Zero options from other generations.
- **SC-004**: In property tests over all reachable identification states (at least 1,000 generated scenarios), 100% of states have a reply that advances them, and no scenario exceeds the bounded number of asks per level.
- **SC-005**: For every version offered or settled from a sourced list, its power is found in a cited document (100% in the test set of at least 6 models).
- **SC-006**: Zero used cars are costed or scored with age 0, and zero used cars have the new price as their purchase price. Measured on the golden dialogues and the replay set.
- **SC-007**: For a used car, every cost line and criterion that depends on age or mileage lists the age and mileage it used, and whether they were stated or assumed (100% of such lines in the test set).
- **SC-008**: A second chat about a model generation already looked up identifies it with no new search (100% within the freshness period).

## Assumptions

- Spain is the only market, as in earlier specs.
- Editorial spec sites (e.g. km77) and official configurators are acceptable sources for the version lists. Classified-ads sites stay forbidden (deny-list).
- **The "most common or base option" rule for "choose for me":**
  - the first version listed by the sources (sources list base versions first);
  - between gearboxes, the one listed first for that engine;
  - between drives, front-wheel drive when offered.
- **Ask limits and defaults:**
  - the default ask limit per level is 2;
  - the default yearly distance for an assumed age is 15,000 km;
  - the default age when nothing is known is 5 years.

  These are configurable.
- Looking up the versions of a model generation costs about one search and one short reading per generation, shared by all chats. It is accepted as part of identification without a separate cost confirmation, within the per-turn hard cap.
- Equipment trim and interior differences are not identified (agreed with the owner). Prices that depend on trim use the base trim of the settled version, as in spec 004.
- Used market prices come from the existing used-price research area. Their sources and limits are unchanged.
- **The PR #45 fixes are kept** ("choose for me" on "remove or choose", options filtered by the year). This spec replaces the mechanism behind them.
- The draft ladder on branch `008-wip-version-ladder` may be reused by the plan if it fits these requirements.
