# Feature Specification: Understanding the User — Car Identification and Intake

**Feature Branch**: `005-user-intake-identification`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "005 — Understanding the user: car identification and intake that works like an expert dealer, not a form." (full text in the commit that created this file; summarised below)

## Background: the incident of 2026-11-03 (chat 5be54966)

The user wrote (in Russian): "How good is BYD — find the matching model — compared with SEAT Ateca, for long-term family
use in the south of Spain, 1–2 thousand km a month, city and motorway, cheap to run, must not break, pleasant to drive."

What happened:

1. The assistant asked "which BYD?". The user answered "BYD Seal U". Then the user sent the official site
   (byd.com). Then explained "BYD is Build Your Dream, Chinese, sold in Europe". Then "compare BYD Seal U with the Ateca
   1.5". **Every time** the assistant answered "I don't know a car called «byd». Did you mean one of these: make and
   model?" — with no options, partly in English, and naming the old text "byd" although "BYD Seal U" had already been
   understood.
2. One reply fell out of the intake into generic chat: it greeted the user ("Hi! I am AutoMind…") in the middle of the
   dialogue and named a model the user never mentioned (BYD Atto 3).
3. The user corrected the SEAT engine ("1.5, you wrote 1.0, that is wrong"). The correction was stored but the car stayed
   "SEAT Ateca 1.0 TSI 110 CV Manual".
4. New or used and the year were never asked or inferred for either car. Region and climate (south of Spain, heat) were
   ignored; part of the profile (family, ~18,000 km/year, city + motorway, priorities) was captured.

Causes found in the code (for the plan, not requirements):
- a make/model absent from the local catalog and configuration is rejected unless the resolver returns a generation for
  the same model; for a new brand the web search gave poor material;
- the re-ask keeps the original request text and does not resolve again after the answer was parsed;
- on the last answer the reply was judged "not understood" and no identification was attempted at all;
- an empty list of alternatives still produced the "did you mean" question; the question text is an English template;
- a confirmed or automatically resolved car is never resolved again after a correction; there is no engine
  (displacement / power / fuel) hint, the engine went into the trim hint;
- an off-topic route ("general") was reachable while a question was pending.

This is the most important step of the product: if the car and the person are misunderstood, every report after it is
wrong. The intake must take **maximum effort** to understand, like an experienced dealer.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Every reply moves the identification forward (Priority: P1)

The user names a car loosely, answers questions in free text, sends a link, explains a brand, corrects a detail or
repeats the request in other words. Each reply is used: what it says about make, model, generation, engine, gearbox,
year, condition or trim is applied, the car is identified again, and the next question (if any) is about what is
still missing — never the same question again.

**Why this priority**: the incident shows the loop failing on four replies in a row. Without this nothing else works.

**Independent Test**: replay the incident chat. After "BYD Seal U" the BYD is identified (or a concrete list of BYD
Seal U versions is offered); no question is repeated; research starts only after confirmation.

**Acceptance Scenarios**:

1. **Given** a pending question "which BYD?", **When** the user answers "BYD Seal U", **Then** the car becomes BYD Seal U
   and the next step offers its versions on sale in Spain (for example the plug-in hybrid DM-i and the electric version)
   or confirms the one that fits the profile.
2. **Given** a pending question about a car, **When** the user answers with a URL of the maker or a model page, **Then**
   the page is read (as untrusted content) and used to identify the car, and the assistant says what it found there.
3. **Given** a pending question, **When** the user explains the brand ("BYD is Build Your Dream, Chinese, sold in
   Europe"), **Then** the assistant accepts the brand, lists the brand's models on sale in Spain as options, and asks
   which one (or offers to pick).
4. **Given** a pending question, **When** the user repeats the whole request in other words ("compare BYD Seal U with
   the Ateca 1.5"), **Then** it is treated as an answer and as a correction together: both cars are updated.
5. **Given** any reply, **When** it contains no usable information, **Then** the assistant says what exactly it needs,
   in other words than before, with concrete options; the same question text is never sent twice in a row.
6. **Given** two failed attempts for one car, **When** the third reply is also unclear, **Then** the assistant proposes
   the most likely concrete car itself ("I'll take BYD Seal U DM-i Comfort 2025, OK?") instead of asking again.

---

### User Story 2 — Open-world brands and models (Priority: P1)

Brands and models that are not in the local catalog (BYD, MG, Omoda, Jaecoo, Chery, Leapmotor, Xpeng, Lynk & Co, Cupra,
EBRO, DFSK, …) are identified from the web (maker's Spanish site, Spanish price lists, reference sites) and offered as
concrete choices. "Find the matching model of this brand for me" is a valid request: the assistant proposes 1–3 models
of that brand that fit the profile and says why.

**Why this priority**: the Spanish market changes fast, mostly through new Chinese brands; a catalog-only identity
locks the user out of exactly the cars they ask about.

**Independent Test**: start a chat with "BYD vs SEAT Ateca for a family"; the assistant offers concrete BYD models on
sale in Spain (with body and powertrain) and, if asked to choose, recommends one with a reason.

**Acceptance Scenarios**:

1. **Given** a make not in the catalog, **When** the user names it, **Then** the assistant finds the models of that make
   on sale in Spain and offers them as options (never "I don't know a car called …" when the make exists).
2. **Given** "find the matching model" for a brand, **When** the profile says family and long distances, **Then** 1–3
   models are proposed with a one-line reason each (size, powertrain, price band), and the user picks or accepts.
3. **Given** a name that does not exist at all, **When** no make or model can be found, **Then** the assistant says so
   plainly and offers the closest real names; if there are none, it asks for the make and model in its own words —
   never an empty "did you mean".
4. **Given** a model name in another script or transliteration ("сеат атека", "хендай туссан", "биад сил ю"),
   **When** it is read, **Then** it is mapped to the real make and model.

---

### User Story 3 — Corrections change the car (Priority: P1)

A correction of any part of the identity ("not 1.0 but 1.5", "automatic", "the diesel", "2025", "the long-range one",
"it is used, 60,000 km") changes the car, the version is identified again, and the change is shown back
("SEAT Ateca 1.0 TSI 110 CV → 1.5 TSI 150 CV DSG").

**Why this priority**: in the incident the correction was ignored; a report on the wrong engine is worthless.

**Independent Test**: resolve "SEAT Ateca", then say "1.5, not 1.0": the car becomes a 1.5 TSI version and the change is
shown; no research runs on the 1.0.

**Acceptance Scenarios**:

1. **Given** a resolved car, **When** the user names another engine (displacement, power, fuel or hybrid type),
   **Then** a version with that engine is selected (or the versions with that engine are offered) and the old one is not
   used any more.
2. **Given** a correction that conflicts with what exists ("Ateca 2.5 diesel"), **When** no such version is sold,
   **Then** the assistant says so and lists the engines that do exist.
3. **Given** a correction during or after research, **When** it changes the identity, **Then** the research and the
   report are for the corrected car; values of the old version are not reused for the new one.

---

### User Story 4 — Full intake: car facts and the person (Priority: P2)

Before research the assistant knows, for each car: make, model, generation, engine (displacement, power, fuel or
electric), gearbox, year, new or used (and mileage if used), and trim level — inferred where possible, asked where
it changes the answer. And it knows the person: who drives and for what (family, commuting, long trips), km per year,
region and climate, budget, priorities, experience, what they want to feel. Each inferred item shows its evidence
(the words that led to it).

**Why this priority**: the incident lost new/used, year and region. Each of these changes prices, reliability and costs.

**Independent Test**: the incident's first message yields: family; city + motorway; 12,000–24,000 km/year
(stated "1–2 thousand km a month"); south of Spain (hot climate); priorities reliability, running cost, comfort;
and one question about new or used (and year) for both cars together.

**Acceptance Scenarios**:

1. **Given** a request without new/used, **When** the intake runs, **Then** new or used is inferred from the words
   ("buy", "replace my old one", a year, a mileage) or asked once for all cars together.
2. **Given** a region ("south of Spain", "Málaga", "Madrid"), **When** the profile is built, **Then** the region and its
   climate are stored with evidence and later used (air conditioning load, battery in heat, fuel prices by region).
3. **Given** "1–2 thousand km a month", **When** read, **Then** the yearly distance is stored as a range
   (12,000–24,000 km) and the middle is used for costs, with the range shown.
4. **Given** the questions needed, **When** they are asked, **Then** at most 3 questions are asked in one message,
   grouped, with quick-reply options, and only those that change the answer.

---

### User Story 5 — One confirmation card before research (Priority: P2)

Before any paid research the assistant shows one card: per car the identity (make, model, generation, engine, power,
gearbox, year, new/used, trim, official price if new) and the person (profile items with evidence). Each item can be
changed by a chip or a free-text reply. Research starts only after "yes".

**Why this priority**: the user sees what will be researched and can fix it in one step; no money is spent on a wrong car.

**Independent Test**: after the intake the card lists both cars and the profile; changing "1.0" to "1.5" on the card
updates it; research starts only after confirming.

**Acceptance Scenarios**:

1. **Given** all cars identified, **When** the card is shown, **Then** every field shown is either confirmed by the user,
   inferred with evidence, or marked "assumed" with the default used.
2. **Given** the card, **When** the user edits a field, **Then** the card is shown again with the change highlighted.
3. **Given** the card, **When** the user confirms, **Then** research starts for exactly the cars on the card.

---

### User Story 6 — The intake stays on task and speaks the user's language (Priority: P2)

During the intake every message is about identifying the cars or the person. No greeting in the middle, no generic
chat, no invented models. All questions, options and notices are in the user's language.

**Why this priority**: the incident's generic reply and English templates made the product look broken.

**Independent Test**: replay the incident in Russian: no English text, no greeting after the first turn, no model the
user did not name or choose.

**Acceptance Scenarios**:

1. **Given** a pending intake question, **When** the user writes anything, **Then** the reply is part of the intake
   (an answer, a correction, a new request or an explicit "stop") — never generic chat.
2. **Given** the user writes Russian, **When** any question or option is sent, **Then** it is in Russian.
3. **Given** the assistant suggests a model, **When** the user did not name it, **Then** it is presented as a suggestion
   with a reason, never as the user's choice.

### Edge Cases

- A brand known only by its Chinese or alternative name (Jaecoo/Omoda/Chery, EBRO built from Chery models).
- A model with the same name under different brands or markets (Seal vs Seal U vs Sealion 7; MG4 vs MG ZS EV).
- The user names a version that is not sold in Spain (imported, US-only): say so, offer the Spanish equivalent.
- The user sends a link to a classifieds site: it is not read (classifieds are never scraped); ask for the car in
  words.
- The user changes the whole request mid-intake ("forget the BYD, compare with the Tucson").
- Plug-in hybrid vs electric versions of the same model (BYD Seal U DM-i vs Seal U EV): treated as different cars.
- The user says "you choose" for the version: the equal-level rule (004 FR-029) picks it and says so.
- The maker's site is in Chinese or blocked by robots.txt: other sources are used.
- Search is down or a limit is reached during the intake: say so and ask whether to continue; never invent.

## Requirements *(mandatory)*

### Functional Requirements

**Identification loop**

- **FR-001**: Every user reply during the intake MUST be parsed for identity facts (make, model, generation, engine,
  gearbox, drive, year, condition, mileage, trim, URL) and for profile facts, and the facts MUST be applied to the case
  before the next question is chosen.
- **FR-002**: After facts are applied, each affected car MUST be identified again from its current facts, not from the
  original request text.
- **FR-003**: The same question (same car, same missing item, same text) MUST NOT be sent twice in a row. A repeated
  missing item MUST be asked differently, with concrete options.
- **FR-004**: After two unsuccessful attempts for one car the assistant MUST propose the most likely concrete car itself
  and ask for a yes/no, instead of asking an open question again.
- **FR-005**: A reply that restates the whole request MUST be treated as both an answer and a correction.
- **FR-006**: A URL in a reply MUST be read (as untrusted content, robots.txt respected, classifieds never read) and used
  as identification evidence; the assistant MUST say what it took from the page.

**Open-world identity**

- **FR-007**: A make or model not in the local catalog MUST be looked up on the web (maker's Spanish site, Spanish price
  lists, reference sites) before it can be declared unknown.
- **FR-008**: For a known make without a model, or a "find the matching model" request, the assistant MUST offer the
  make's models on sale in Spain (at most 6) with body type and powertrain, and, when asked to choose, recommend 1–3
  with a one-line reason from the profile.
- **FR-009**: "Unknown" MAY be said only after the lookup; it MUST offer the closest real names, or, if there are none,
  ask in plain words. An empty list of options MUST never be shown.
- **FR-010**: Names in other scripts and transliterations MUST be mapped to real makes and models.
- **FR-011**: New identities found on the web MUST carry their sources and enter the catalog like any other (no invented
  versions, constitution I and II).

**Corrections**

- **FR-012**: The identity MUST include the engine: displacement, power, fuel or electric type, hybrid type.
- **FR-013**: A correction of any identity part MUST re-identify the car even if it was resolved or confirmed; the old
  version MUST NOT be used afterwards in this chat.
- **FR-014**: The change MUST be shown back as "before → after".
- **FR-015**: A correction that matches no version on sale MUST be answered with the versions that exist.

**Intake of the person**

- **FR-016**: The profile MUST include who drives and for what, km per year (as a range when given as a range), region
  and climate, budget, priorities, experience and wanted feel; each inferred item MUST carry its evidence words.
- **FR-017**: New or used MUST be inferred from the words or asked once for all cars together; the year MUST be asked
  for a used car and inferred as "current" for a new one.
- **FR-018**: At most 3 questions MUST be asked per message, grouped, each with quick-reply options, and only questions
  whose answer changes the identification or the report.

**Confirmation**

- **FR-019**: Before research the assistant MUST show one confirmation card: per car the identity and official price
  (if new), and the profile; every item marked as stated, inferred (with evidence) or assumed.
- **FR-020**: Every card item MUST be changeable by a chip or free text; the card MUST be shown again after a change with
  the change highlighted.
- **FR-021**: Research MUST start only after the user confirms the card, and only for the cars on it.

**Staying on task**

- **FR-022**: While an intake question is pending, replies MUST NOT be routed to generic chat; a greeting MUST NOT appear
  after the first assistant message.
- **FR-023**: All intake text (questions, options, notices, cards) MUST be in the conversation language; no template in
  another language may leak.
- **FR-024**: A model the user did not name MUST be shown only as a suggestion with a reason.

**Measurement**

- **FR-025**: For each chat the system MUST record: user replies until a confirmed identity, repeated questions,
  corrections and whether each changed the identity, research started on an unconfirmed car.

### Key Entities

- **Car identity**: make, model, generation, engine (displacement, power, fuel/electric, hybrid type), gearbox, drive,
  year, condition, mileage, trim and trim level, official price if new; each with its source (stated, inferred with
  evidence, assumed, looked up with a source).
- **Identity fact**: one piece of identity or profile from one reply, with the words it came from.
- **Intake attempt**: a question asked about one missing item of one car, its text and the reply; used to avoid repeats.
- **Brand line-up**: the models of a make on sale in Spain (body, powertrains, price band) with sources and the date.
- **Person profile**: usage, km/year range, region and climate, budget, priorities, experience, wanted feel, each with
  evidence.
- **Confirmation card**: the cars and the profile as shown, with the user's edits and the final "yes".

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the golden dialogues (the incident chat plus at least 8 similar: unknown brand, engine correction, URL
  answer, transliteration, "find a model for me", used with mileage, EV vs combustion, region and climate) 100% reach a
  confirmed, correct identity for every car.
- **SC-002**: At least 90% of chats reach a confirmed identity within 3 user replies.
- **SC-003**: Zero identical questions sent twice in a row in the goldens and in live chats.
- **SC-004**: Zero research runs started on an unconfirmed car or on a version the user corrected away from.
- **SC-005**: Zero intake messages in a language other than the conversation's; zero mid-dialogue greetings.
- **SC-006**: For the 10 largest brands on sale in Spain that are not in the catalog today, naming the brand yields its
  real line-up as options in 100% of the tries.
- **SC-007**: Every correction in the goldens changes the identity and is shown back as "before → after".
- **SC-008**: The time from the first message to the confirmation card is under 60 seconds when no question is needed.

## Assumptions

- Spain is the market for prices, line-ups and dealer data, as in specs 002–004.
- The intake may use paid search and model calls; the existing limits apply and ask "continue?" instead of cancelling.
- Classifieds are never read, also when the user sends a link to them.
- The equal-level rule of spec 004 (FR-029) stays: no trim named → the cheapest base version.
- Profile questions stay optional; identity questions block research.
- Data for electric and plug-in hybrid cars (battery, range, charging) is the next spec; 005 only identifies them
  correctly.

## Roadmap — all steps ahead (in order)

Each step is its own spec (or a short follow-up), opened in a new session: specify → clarify → plan → tasks →
implement → live check.

1. **005 — Understanding the user** (this spec): identification loop, open-world brands, corrections, full intake,
   confirmation card, staying on task.
2. **004 leftovers**: live golden dialogues G12–G20 and the manual RAV4 / CX-5 / CR-V check on paid Gemini (announced
   with a cost estimate first); localise the remaining backend texts (case summary facts, data panel areas,
   explainers); the comparison table as its own block.
3. **006 — Electric, plug-in hybrid and Chinese brands data**: battery size and chemistry, real range (WLTP and
   real-world, heat and cold), charging (AC/DC power, 10–80% time), energy cost at home and public, battery warranty,
   dealer and service network in Spain, residual value of EVs.
4. **007 — Used-car mode**: mileage and age, known issues by year and engine, recalls, maintenance due at a given
   mileage, price ranges from editorial and analyst sources (never classifieds).
5. **008 — Accounts and per-user history**: login, own chats and cases, deletion; required before the app is reachable
   outside the local network.
6. **009 — Cost and speed**: caching of searches and pages across chats, cheaper models per role, time to first useful
   answer, cost per report shown and bounded.
7. **010 — Observability and quality dashboard**: ratings, rejected claims by rule, text/block contradictions,
   repeated questions, corrections, cost per chat — one page.
8. **011 — Deployment beyond the local network**: HTTPS, domain, backups, monitoring, update procedure.
