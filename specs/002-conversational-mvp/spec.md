# Feature Specification: AutoMind Conversational MVP

**Feature Branch**: `002-conversational-mvp`

**Created**: 2026-11-01

**Status**: Draft (supersedes `specs/001-car-battle-mvp`)

**Input**: User description: "AutoMind conversational MVP: a chat-first automotive research system
where the user talks to a hub agent (car expert) that keeps a persisted case file per chat
(persona, new/used, age, budget, usage, weighted priorities, cars, results shown), chooses each
turn whether to ask, answer from context, correct a car, research gaps, or report; maps wishes to
criteria; researches technical data, maintenance, reviews, reliability, official price, and the
manufacturer with research-grade validation; computes metrics, drag race, ownership cost and
scores deterministically; and produces persona-specific reports as chat text plus visual blocks."
Full input: `docs/vision.md` (§1–§7, including §5a lessons from the concept demo) and constitution
v1.1.1.

## Clarifications

### Session 2026-11-01

- Q: How should the hub learn who the user is (persona)? → A: Infer it from the user's wording. If it is unclear, include one persona question in the single clarification round (max 3 questions). Until then the persona is "unknown".
- Q: When must resolved variants be confirmed before web research? → A: Only when the variant is ambiguous, is a used car (generation depends on year), or is not in the catalog. Unambiguous variants that are cached and fresh proceed without confirmation.
- Q: Which measurable indicators define "status"? → A: Price class (official new price) + vehicle segment + brand positioning (premium/mainstream/budget) from cited sources; for used cars, adjusted for the age of the generation.
- Q: How is the repair reserve for a used car computed in the ownership cost? → A: Known big-ticket items for that generation, age and mileage (sourced) plus a base reserve from a configurable age-band × vehicle-class table (labelled assumption).
- Q: How are AI and search costs controlled when the hub decides to research more? → A: Estimate the cost before research. Below a threshold (default €0.30 per turn) proceed; above it, ask the user to confirm, showing the estimate; a hard cap per turn (default €1.00) is never exceeded.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The expert understands me and remembers the conversation (Priority: P1)

A user writes in their own words, for example: *"I don't want to spend too much, but I don't
want rubbish either. A brand-new Dacia Bigster or a used Land Cruiser Prado?"* The hub builds a
**case file**:
- who the user is (persona);
- new or used, and approximate age or years;
- budget, if stated;
- usage;
- priorities;
- the cars under discussion.

When something essential is missing or ambiguous (e.g. "used Prado" without age, which spans two
generations), it asks 1–3 short clarifying questions instead of guessing. It confirms the exact
variants before expensive research ("Prado 150, 2013–2016, 3.0 D-4D?"). Later messages update the
case file instead of starting over:
- "I meant the 150, not the 250" replaces the car;
- "status matters to me" adds a priority;
- "I'm 20 and drive in the mountains" updates persona and usage.

The user can see the case file and edit it.

**Why this priority**: The concept demo showed that without this the system is "deaf": it
researched a new Prado J250 twice when the user wanted a used Prado 150, ignored who the user
was, and repeated reports. Everything else depends on understanding the user correctly.

**Independent Test**: Replay the golden dialogues (FR-046). After each turn, verify:
- the case file contents;
- the action the hub chose (ask / answer from context / correct / research / report);
- the variants resolved.

These checks need no live web research; cached data is enough.

**Acceptance Scenarios**:

1. **Given** a new chat, **When** the user asks "new Dacia Bigster or a used Land Cruiser
   Prado?", **Then** the hub asks at most 3 clarifying questions, at least one about the Prado's
   age or generation, and records "Bigster: new", "Prado: used" in the case file without starting
   research yet.
2. **Given** the user answers "about 10 years old, the 150", **When** the hub proceeds, **Then**
   it resolves the Prado to the 150-series generation matching that age, reusing the catalog
   entry if one exists. It shows the resolved variants for confirmation before researching
   anything not already cached and fresh.
3. **Given** a comparison was shown for a wrong variant, **When** the user says "I asked about
   the used 150, not the 250", **Then** the hub classifies this as a correction. It replaces the
   car, keeps the other car and every other part of the case file, and does not repeat the
   previous report.
4. **Given** a comparison has been shown, **When** the user says "if I prefer status, who
   wins?", **Then** the hub adds "status" with a weight to the case file. It answers from
   already-collected data by recomputing the scores, with no new web research unless the status
   criterion lacks data. It states which status indicators were used.
5. **Given** the user says "I'm 20, I can buy a used BMW 320d M Sport or a Golf R-Line 4Motion",
   **When** the hub replies, **Then** the case file records the age and the used/new state, and
   the report reflects that persona (FR-030).
6. **Given** a chat was closed or the application restarted, **When** the user returns to the
   chat, **Then** the history and the case file are restored and the conversation continues with
   full context.
7. **Given** the user edits the case file directly (e.g. removes a priority or changes the
   budget), **When** they send the next message, **Then** the hub uses the edited case file.

---

### User Story 2 - Research-grade comparison of 2–3 cars (Priority: P2)

Once the cars are confirmed, the system researches what the case file needs:
- technical data;
- scheduled maintenance;
- reviews;
- reliability;
- official Spanish price;
- manufacturer.

It reuses cached, validated data that is still fresh. Every value carries its source, a
provenance label and a confidence level. When the minimum evidence for a section isn't reached
after bounded follow-up research, the section says "insufficient data" instead of guessing. The
user sees live progress and can choose research depth (Quick / Standard / Deep).

**Why this priority**: Trustworthy, validated data is the product's promise (constitution I, XI).
Without it, reports are opinions.

**Independent Test**: Research 2 cars at Standard depth, then verify:
- every value has a source and labels;
- sections below the minimum show "insufficient data";
- a repeat request within the freshness period runs no new web research for those cars.

**Acceptance Scenarios**:

1. **Given** confirmed cars, **When** research runs, **Then** the user sees per-car progress
   (searching, reading N sources, validating, follow-up for missing items) and the research
   completes even if individual sources fail.
2. **Given** a value was extracted from a source, **When** validation runs, **Then** it is
   accepted only if the quoted excerpt occurs in the source and contains the value, the source
   refers to the same variant, and the unit is valid. Generation-wide ranges ("1381–1502 kg") are
   never accepted as a variant value.
3. **Given** sources disagree, **When** values are selected, **Then** the authority order and
   majority rules apply (FR-017). Unresolved conflicts are shown with all competing values.
4. **Given** critical data for the case file's criteria is missing after the first round,
   **When** follow-up research runs, **Then** it targets exactly the missing items. It stops at
   the depth level's round limit and reports what remains unavailable.
5. **Given** a car's data is cached and fresh, **When** it appears in a new comparison, **Then**
   only stale or missing categories are researched.

---

### User Story 3 - A report for who I am, with criteria I understand (Priority: P3)

The answer is tailored to the persona and the priorities in the case file:
- **Expert**: engineering depth (powertrain architecture, chassis, design, manufacturer
  background).
- **Performance enthusiast**: dynamics, power-to-weight, measured vs claimed performance, drag
  race.
- **Everyday or family buyer**: plain language about reliability, ownership cost, practicality,
  comfort and value.

The user's wishes become **criteria with visible weights** (e.g. reliability 30%, ownership cost
25%, status 15%). The user can adjust the weights, and scores update without new research.

**Why this priority**: The same report for everyone was a key demo failure. Visible criteria make
the verdict explainable and adjustable.

**Independent Test**: Use the same two cached cars with three personas. Verify different report
sections, depth and wording; criteria and weights derived from stated wishes; and recomputed
scores after a weight change, with no new research.

**Acceptance Scenarios**:

1. **Given** a case file with persona "everyday buyer" and priorities "reliability, low cost",
   **When** the report is produced, **Then** it leads with reliability and ownership cost in
   plain language. It shows the criteria with weights, and a score per car with the contribution
   of each criterion.
2. **Given** persona "expert", **When** the report is produced, **Then** it includes engineering
   details (engine or motor architecture, transmission, chassis and suspension, platform) with
   sources, and a manufacturer section.
3. **Given** the user changes a weight, **When** they confirm, **Then** the scores and verdict
   are recomputed from existing data and shown, with no web research.
4. **Given** a criterion has no data for a car, **When** scoring runs, **Then** that criterion is
   shown as "insufficient data" for that car. A car whose criteria are covered less than the
   minimum share (default 60% of weight) is not ranked, with an explanation.
5. **Given** a wish that maps to no defined criterion (e.g. "nice colour"), **When** the hub
   processes it, **Then** it says this cannot be assessed with data and does not invent a score.

---

### User Story 4 - What will it cost me to own? (Priority: P4)

For buyers, the system produces an **ownership cost report**: annual and 5-year cost covering:
- scheduled maintenance (intervals, work items, cost when published);
- energy (fuel or electricity);
- tyres;
- road tax (if found);
- for used cars, big-ticket items due at that age or mileage (e.g. timing belt, gearbox service,
  suspension, corrosion checks) and a repair reserve.

Each figure is labeled as sourced or as an assumption, with its inputs shown.

**Why this priority**: The demo had only a rudimentary service-plus-fuel estimate; buyers need a
real picture, especially for used cars.

**Independent Test**: Run a TCO for one new and one ~10-year-old used car. Verify the annual and
5-year totals, the item breakdown, sourced vs assumption labels, and the age-related items for
the used car.

**Acceptance Scenarios**:

1. **Given** a car with a published maintenance schedule, **When** the TCO is computed, **Then**
   intervals and items come from sources. Costs not found are computed from configured rates and
   labeled "assumption" with their inputs.
2. **Given** a used car of a stated age and mileage, **When** the TCO is computed, **Then** it
   lists age- or mileage-related items that are due or likely within 5 years, with sources where
   available, and includes a labeled repair reserve.
3. **Given** the user states their annual mileage, **When** the TCO is recomputed, **Then** it
   uses that mileage instead of the default.

---

### User Story 5 - Reliability and reviews (Priority: P5)

The system summarizes, per variant:
- **known technical issues**, marked recurring or isolated, with the affected component and
  sources;
- **reliability statistics** where available (e.g. breakdown or inspection statistics);
- **expert and owner reviews**: pros and cons, with recurring points separated from isolated
  opinions.

For used cars, issues relevant to the generation and age are emphasized.

**Why this priority**: Reliability is a top concern for buyers and for "not rubbish" decisions,
but it builds on the research foundation (US2).

**Independent Test**: For a variant with a well-documented issue, verify the issue appears with
sources and classification, reviews are summarized with sources, and a variant without documented
issues says "no documented issues found".

**Acceptance Scenarios**:

1. **Given** completed research, **When** the reliability section is shown, **Then** each issue
   has a component, description, recurrence class and ≥1 source. "Recurring" requires ≥2
   independent sources.
2. **Given** reviews were collected, **When** they are summarized, **Then** pros and cons cite
   their sources, and the summary meets the review minimum (default ≥5 reviews from ≥2 sources)
   or is marked "insufficient data".

---

### User Story 6 - Performance lab: drag race (Priority: P6)

Performance enthusiasts can run a drag race between the cars:
- **settings**: dry or wet surface, extra load, temperature, altitude;
- **prediction**: optional, the user predicts the winner before the run;
- **result**: speed, distance and acceleration over time; 0–100 and 0–200 km/h, 400 m time and
  finishing speed; claimed and measured figures alongside.

Results are labeled "simulated estimate", with the model version and assumptions.

**Why this priority**: Engaging and already proven in the demo; important for one persona.

**Independent Test**: Run the same race twice and verify identical results. Then run wet with
+200 kg and verify slower times and the displayed settings, and the prediction compared.

**Acceptance Scenarios**:

1. **Given** cars with power and weight, **When** the race runs, **Then** charts, a results table
   and a finishing order are shown, labeled "simulated estimate", with assumptions listed.
2. **Given** a car lacks power or weight, **When** the race runs, **Then** that car is excluded
   with an explanation and the others still race.
3. **Given** the same inputs and model version, **When** the race is re-run, **Then** the results
   are identical.

---

### User Story 7 - Progress, limits, history (Priority: P7)

The user sees what the system is doing at each step, without internal model reasoning. They see
the AI usage and estimated cost per turn, and can cancel a running research. Past chats are
listed and can be reopened or continued. Interrupted research continues after a restart.

**Why this priority**: Needed for a reliable product; partly proven in the demo.

**Independent Test**: Start a research, then:
- watch the progress events;
- restart the application mid-research and verify that it continues without redoing completed
  work;
- cancel another research and verify that it stops;
- reopen an old chat.

**Acceptance Scenarios**:

1. **Given** a running research, **When** the user cancels, **Then** no new work starts, and
   already validated data stays cached and usable.
2. **Given** a restart during research, **When** the application is back, **Then** the research
   continues and completed per-car work is not repeated.
3. **Given** any completed turn, **When** the answer is shown, **Then** the number of AI calls,
   tokens and estimated cost for that turn are visible.

---

### Edge Cases

- **Ambiguous model** ("Prado" without age; "Golf" without trim): the hub asks or proposes the
  most likely variant with alternatives. It never silently picks the newest generation for a
  stated used purchase.
- **Contradictory statements** (budget changes, new vs used flips): the latest statement wins,
  the case file shows the change, and the hub mentions it if it changes conclusions.
- **More than 3 cars requested**: the hub asks which 3 to compare.
- **Car not sold in Spain**: the market difference is stated explicitly.
- **Pasted URL**: used to identify the variant and as a first source. Deny-listed sites
  (classifieds) are not fetched.
- **Off-topic or general questions** ("how does a turbo work?"): answered as general knowledge,
  labeled "no sources", with no car-specific numbers.
- **"Status"-type subjective wishes**: mapped to defined measurable indicators (FR-028). If no
  data exists, the answer says so.
- **Budget limit or round limit reached**: the turn completes with what is available and states
  which limit was reached.
- **Used car older than 25 years**: sources are scarce, so the system warns early that many
  sections may be "insufficient data".
- **User writes in Russian, Spanish or English**: replies come in the same language; data labels
  stay consistent.
- **Duplicate catalog entries for the same variant** must not occur. Equivalent names resolve to
  one variant.

## Requirements *(mandatory)*

### Functional Requirements

**Conversation and case file (US1)**

- **FR-001**: The system MUST provide a chat in which the user writes free text in Russian,
  Spanish or English and receives replies in the same language.
- **FR-002**: The system MUST maintain one **case file** per chat. It contains: persona (expert,
  performance enthusiast, everyday or family buyer, or unknown), age and experience if stated,
  new/used per car, model years or age, mileage, budget, usage (city, motorway, mountains,
  off-road, track, family), weighted priorities, cars under discussion with their resolved
  variants, research depth, and a log of results already shown.
- **FR-003**: Every user message MUST be interpreted against the case file and update it. The
  latest explicit statement wins over earlier ones, and changes are recorded.
- **FR-004**: For each turn the hub MUST choose exactly one primary action and record it:
  **ask**, **answer from context**, **correct**, **research**, or **report**. A report MUST NOT
  be repeated unchanged when the case file has not changed. The hub explains what is new
  instead.
- **FR-005a**: The persona MUST be inferred from the user's wording (e.g. age, "want to race",
  "family", "don't want to overpay", technical vocabulary). If it cannot be inferred and it
  affects the answer, a persona question MUST be included in the same clarification round as
  other questions (still at most 3 questions). Until then the persona is "unknown", and reports
  use a balanced default layout. The hub MUST NOT open a new chat with a persona questionnaire.
- **FR-005**: The hub MUST ask 1–3 clarifying questions when information that changes the result
  is missing or ambiguous: generation or age for a used car, which trim, more than 3 cars, or a
  conflicting new/used statement. Otherwise it MUST proceed and state its assumptions. It MUST
  NOT ask more than one round of questions before giving a useful answer unless the user's
  answer creates a new ambiguity.
- **FR-006**: Before web research, the hub MUST show the resolved variants (make, model,
  generation, years, engine or motor, new/used) and wait for confirmation or correction in the
  chat when **any** of these holds:
  - the resolution is ambiguous;
  - the car is used (generation depends on year or age);
  - the variant is not yet in the catalog.

  Variants that are unambiguous and already cached and fresh MUST proceed without confirmation.
  The resolved variant is always shown in the answer.
- **FR-007**: Corrections ("not the 250, the 150", "the diesel one", "remove the BMW") MUST
  replace or modify only the referenced car. Resolution MUST search the local catalog first.
- **FR-008**: Variant resolution MUST use the case file's age, year and new/used context. For a
  used car of a given age, the generation sold in those years MUST be chosen (or offered as
  options).
- **FR-009**: The case file MUST be visible to the user in the interface and editable (persona,
  usage, budget, priorities and weights, annual mileage, depth). Edits apply from the next turn.
- **FR-010**: Chat history and case file MUST persist across sessions and application restarts.
- **FR-011**: General automotive questions not about specific researched cars MUST be answered
  as general knowledge, labeled "no sources", without car-specific figures.

**Research and validation (US2)**

- **FR-012**: The system MUST support comparisons of 1–3 cars. A single car gets a profile
  report: the same persona-ordered blocks and criteria scores (absolute, against the criteria
  scales), with no ranking, winner or race; 2–3 cars get a comparison.
- **FR-013**: Research areas MUST include:
  - technical data (Tier 1 core specs, Tier 2 engineering details, Tier 3 measured performance);
  - scheduled maintenance (intervals, items, costs if published);
  - expert and owner reviews;
  - reliability (known issues, published statistics, recurring complaints);
  - the official manufacturer price in Spain (with date, trim, taxes);
  - the manufacturer (history, key models, market position);
  - practicality (boot, seats, consumption or range).
- **FR-014**: Research MUST be **driven by the case file**. Areas and attributes needed by the
  current criteria and persona are researched first. Areas not needed MAY be skipped.
- **FR-015**: Every collected value MUST carry: value, unit, source name and link, source type,
  retrieval date, verbatim excerpt, the variant it refers to, a provenance label, and a
  confidence level (HIGH / MEDIUM / LOW per FR-018).
- **FR-016**: A value MUST be accepted only if the excerpt occurs in the source and contains the
  value, the source refers to the same variant, and the unit is valid. Generation-wide ranges
  MUST be rejected as variant values. Rejections MUST be counted and shown in progress.
- **FR-017**: Conflicting values MUST be resolved only by these rules:
  1. authority order: manufacturer > independent instrumented test (performance figures only) >
     established publication > encyclopedia or spec database;
  2. if the highest-ranked sources disagree, the value agreed by ≥2 independent sources of that
     rank wins;
  3. otherwise the conflict stays unresolved and all values are shown.
- **FR-018**: Confidence rules:
  - **HIGH**: a manufacturer source, or ≥2 independent sources agreeing within tolerance;
  - **MEDIUM**: a single non-manufacturer source;
  - **LOW**: an unresolved conflict, or weak or indirect evidence (snippet only, or stated only
    for the generation or engine).

  Confidence MUST NOT be presented as a probability.
- **FR-019**: Each report section MUST have a minimum evidence requirement:
  - key specs: a manufacturer source plus 1 independent source, or 2 independent sources;
  - maintenance: the manufacturer schedule, or 2 independent sources;
  - reviews: ≥5 reviews from ≥2 sources;
  - reliability: ≥2 independent sources.

  Sections below the minimum after research MUST be marked "insufficient data".
- **FR-020**: Missing items MUST trigger targeted follow-up research. The number of rounds is
  bounded by the depth level (Quick: 0, Standard: 1, Deep: 2 by default). Items still missing
  MUST be reported as unavailable, never guessed.
- **FR-021**: Research MUST be cache-first. Validated data is reused while fresh, with freshness
  configurable per category. Defaults: specs (incl. engineering, practicality and measured
  performance) 365 days, maintenance 365, reliability, used-car issues and reviews 180, official
  price 30, manufacturer 30. Only stale or missing categories are researched.
- **FR-022**: Classified-ads and other sites whose terms forbid automated access MUST NOT be
  fetched. Secondary-market prices are out of scope.
- **FR-023**: One car's research failing MUST NOT fail the turn. The failure is shown and the
  other cars continue.
- **FR-024**: The catalog MUST NOT contain duplicate entries for the same variant. Equivalent
  names and spellings resolve to one variant.

**Criteria, scoring and reports (US3)**

- **FR-025**: The system MUST provide a **criteria dictionary**. Each criterion has a definition,
  the data it uses, and a deterministic scoring scale. It covers at least: reliability,
  ownership cost, purchase price, practicality, comfort, performance, driving fun, traction and
  all-weather, off-road and mountain capability, efficiency, safety (if rated), status, and
  engineering sophistication.
- **FR-026**: The hub MUST map the user's wishes and persona to criteria with proposed weights.
  It shows them, and the user can adjust them. Weights are normalized to 100%.
- **FR-027**: Scores MUST be computed deterministically from validated data: a 0–100 index per
  criterion and in total, with each criterion's contribution shown. A criterion without data for
  a car MUST be shown as "insufficient data". A car with less than the minimum covered weight
  (default 60%) MUST NOT be ranked.
- **FR-028**: Subjective wishes MUST be mapped only to measurable indicators defined in the
  dictionary, and the indicators used MUST be named in the answer. The **status** criterion uses
  exactly these indicators:
  - price class (official new price, or the original new price for a used car's generation);
  - vehicle segment;
  - brand positioning (premium / mainstream / budget) taken from cited sources.

  For used cars, an age adjustment for the generation applies (a defined, versioned rule). Wishes
  with no defined indicator MUST be reported as not assessable.
- **FR-029**: Changing weights or priorities MUST recompute scores and the verdict from existing
  data without web research, unless a newly added criterion lacks data.
- **FR-030**: Reports MUST adapt content, depth and wording to the persona:
  - **expert**: engineering details and manufacturer section;
  - **performance enthusiast**: dynamics, measured vs claimed figures, drag race;
  - **everyday or family buyer**: plain-language reliability, ownership cost, practicality and
    comfort, verdict first.
- **FR-031**: Every number in AI-written text MUST appear in the validated or computed data
  within display rounding. Sentences that fail this check MUST be removed, and the removal noted.
- **FR-032**: Reports MUST be shown as chat text plus visual blocks: spec table with sources and
  labels, derived metrics, criteria and score breakdown, TCO, reliability and issues, reviews
  summary, drag race (when relevant), sources list, and notices.

**Ownership cost (US4)**

- **FR-033**: The system MUST compute annual and 5-year ownership cost per car, itemized:
  scheduled maintenance, energy, tyres, road tax (if a rate is found), and for used cars
  age/mileage big-ticket items and a repair reserve.
- **FR-034**: Every TCO item MUST be labeled "sourced" or "assumption", with its inputs shown.
  Configured rates (fuel and electricity prices, labour rate, annual mileage) MUST be visible and
  editable via the case file.
- **FR-035**: For used cars, items due or likely within 5 years given the stated age and mileage
  MUST be listed with sources where available. The repair reserve MUST consist of:
  - (a) these known big-ticket items for the generation, age and mileage, labelled sourced (with
    cost if found, otherwise an assumption cost with inputs);
  - (b) a base reserve from a configurable age band × vehicle class table (€ per year), labelled
    assumption.

  The two parts MUST be shown separately.

**Reliability and reviews (US5)**

- **FR-036**: Known technical issues MUST be listed per variant with component, description,
  sources and recurrence ("recurring" requires ≥2 independent sources). Subjective opinions MUST
  NOT be listed as issues.
- **FR-037**: Review summaries MUST separate recurring pros and cons from isolated opinions and
  cite sources. With no documented issues, the system MUST say "no documented issues found", not
  that the car has none.

**Drag race (US6)**

- **FR-038**: The drag race MUST provide powertrain-specific behavior (combustion, electric,
  hybrid with combined system power), race settings (surface, extra load 0–500 kg, temperature,
  altitude), an optional prediction, time series, 0–100 and 0–200 (or "not reached"), 400 m time
  and speed, and finishing order.
- **FR-039**: Race results MUST be labeled "simulated estimate", show the model version and
  assumptions, appear next to claimed and measured values, and be identical for identical inputs
  and model version.

**Progress, limits, history (US7)**

- **FR-040**: The user MUST see live progress per turn and per car (understanding, asking,
  resolving, cache, researching, validating, follow-up, computing, composing) without internal
  model reasoning.
- **FR-041**: Each turn MUST be bounded by configurable limits: AI calls, follow-up rounds,
  concurrency, timeouts. Before starting research, the hub MUST estimate the turn's cost (cars ×
  areas × depth).
  - If the estimate is below the confirmation threshold (default €0.30), research proceeds.
  - Otherwise the hub asks the user to confirm, showing the estimate, cars, areas and depth.
  - A hard cap per turn (default €1.00) MUST never be exceeded.

  When any limit is reached, the turn completes with available data and states the limit.
  Thresholds are configurable.
- **FR-042**: AI calls, tokens and estimated cost MUST be recorded and shown per turn, counting
  every role, including analyst agents.
- **FR-043**: The user MUST be able to cancel a running research. Validated data collected so far
  stays cached.
- **FR-044**: Interrupted research MUST continue after an application restart without redoing
  completed per-car work.
- **FR-045**: Past chats MUST be listed, with reopen and continue.

**Quality assurance**

- **FR-046**: A set of **golden dialogues** MUST be maintained and run as regression tests,
  including at least:
  - (a) new Dacia Bigster vs used Land Cruiser Prado, with the clarification and a correction to
    the Prado 150;
  - (b) a 20-year-old choosing a used BMW 320d M Sport vs Golf R-Line 4Motion for a drag race,
    city and mountains;
  - (c) "if I prefer status, who wins?" after a comparison;
  - (d) Golf GTI Mk8 vs i30 N for a performance enthusiast, then "and for a smart buyer?" from
    cache;
  - (e) adding a third car.

  Each turn has expected case-file changes, an expected action and expected variants.

### Key Entities

- **Chat**: a conversation with its messages, case file, and per-turn records.
- **Case File**: the structured understanding of the user and task (FR-002), versioned per turn
  with recorded changes.
- **Turn**: one user message and the system's chosen action, progress, answer, blocks, usage and
  limits reached.
- **Persona**: expert / performance enthusiast / everyday-family buyer / unknown, with optional
  age and experience.
- **Criterion**: a dictionary entry with definition, data inputs, scoring scale and version.
  Weighted per case file.
- **Vehicle Variant**: exact identity (make, model, generation, years, trim, powertrain, market),
  unique in the catalog. Separate from data.
- **Car in Case**: a variant plus case context (new/used, age, mileage).
- **Evidence / Claim / Selected Value**: source record, extracted statement with excerpt, and the
  chosen value with provenance, confidence, conflict and alternatives.
- **Research Run**: per variant and category, with freshness, rounds used, and accepted and
  rejected counts.
- **Technical Issue / Review Summary / Reliability Statistic**: per variant, with sources and
  recurrence.
- **Ownership Cost Estimate**: itemized annual and 5-year cost, each item sourced or assumption,
  with inputs.
- **Simulation**: drag race run with model version, settings, prediction, inputs, assumptions and
  results.
- **Golden Dialogue**: a scripted conversation with expected case-file states, actions and
  variants.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of golden dialogues (FR-046) pass: the expected action, case-file changes and
  resolved variants hold at every turn.
- **SC-002**: In golden dialogues, the hub never researches or reports a car the user has
  corrected away from. It never repeats an unchanged report: 0 occurrences.
- **SC-003**: For used-car requests with a stated age or year, the correct generation is
  resolved (or offered as an option) in ≥95% of a test set of ≥20 such requests.
- **SC-004**: Follow-up questions about cars already researched and fresh are answered without
  web research in 100% of cases and within 15 seconds in 90% of cases.
- **SC-005**: A new 2-car comparison at Standard depth completes within 3 minutes in 90% of runs
  under normal source availability.
- **SC-006**: 100% of displayed values carry a provenance label. 100% of sourced values link to
  ≥1 evidence record. 0 values appear without a source, derivation or "assumption" label.
- **SC-007**: On a reference set of ≥20 variants, ≥80% of Tier 1 values are found and ≥95% of
  found values match the reference within tolerance.
- **SC-008**: Personas produce visibly different reports. For the same cars, the report sections
  and ordering differ between the three personas in 100% of golden-dialogue checks.
- **SC-009**: Weight changes recompute the verdict in under 5 seconds with no web research.
- **SC-010**: Every TCO item is labeled sourced or assumption (100%), and used-car TCOs list
  age-related items in 100% of test cases where sources document them.
- **SC-011**: Identical race inputs give identical results (100%). Simulated 0–100 is within ±15%
  of measured values for ≥80% of reference vehicles before being called realistic.
- **SC-012**: Per-turn AI usage shown to the user matches recorded usage across all roles
  (100%).
- **SC-013**: After a restart, 100% of interrupted research continues and no completed per-car
  work is repeated.
- **SC-014**: In a usability check with at least 3 people (e.g. family members with different
  personas), each completes "describe what I want → get a tailored recommendation" without help,
  and rates the answer as relevant to them in ≥4 of 5 cases.
- **SC-015**: No turn exceeds the hard cost cap, and no research estimated above the confirmation
  threshold starts without user confirmation (100% of test cases).

## Assumptions

- **Single local user** (family use), no accounts. The design does not block multiple users
  later.
- **Market**: Spain (ES) by default. Official prices are manufacturer recommended retail prices.
  No secondary-market listings.
- **Cost defaults**: confirmation threshold €0.30 per turn, hard cap €1.00 per turn; estimates
  use the configured model and search prices.
- **Depth default**: Standard. The hub may suggest Deep for used cars older than 10 years.
- **Clarification policy**: at most one round of 1–3 questions before a useful answer (FR-005).
  Otherwise proceed with stated assumptions.
- **Personas**: three personas plus "unknown", inferred from wording (FR-005a). Users can change
  it in the case file.
- **Criteria dictionary v1**: defined and versioned in the plan. Weights are proposals the user
  can change.
- **Status criterion**: price class + segment + sourced brand positioning, age-adjusted for used
  cars (FR-028). There is no "prestige" score without evidence.
- **TCO defaults**: base repair reserve table by age band (0–4, 5–9, 10–14, 15+ years) × class
  (small, compact, mid/large, premium/SUV/4x4), configurable; annual mileage 15,000 km; ES fuel and electricity prices and labour rate as
  configured values (labeled assumptions); tyre life by class.
- **Comparison size**: 1–3 cars (1 = single-car profile report). This changes the earlier 2–4.
- **Interface**: English UI; chat in the user's language; desktop and phone browsers.
- **Carried over from spec 001 and the demo**: catalog reuse, conflict rules, confidence rules,
  provenance labels, excerpt validation, drag race v0.1 with settings and prediction, number check
  on AI text.
- **Out of scope**: secondary-market prices, import of own PDFs, data access for third-party AI
  clients, game-engine visuals, multi-user accounts, report export.
