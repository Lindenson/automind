# Feature Specification: Report Experience — a vivid, personal, trustworthy report and a real dialogue

**Feature Branch**: `004-report-experience`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "Report experience: a vivid, personal, trustworthy report and a real dialogue
(user experience and report algorithms). Verdict first; rich, specific content (technology and engineering
differences, depreciation and residual values, manufacturer situation, ownership cost over time, model-year
changes); report algorithms reviewed and redesigned (deterministic insights before the AI writes, no
contradictions); data gaps handled in the open with a 'find it' action; profile inferred with evidence and
1–3 targeted questions; follow-up suggestions; 'this is wrong' on any value; critique always leads to action;
live research progress grid; UI in the user's language and good on phones."

## Context and Problem

Specs 002 (conversational hub) and 003 (search and data quality) are implemented. Live use on
2026-11-02 (new Toyota RAV4 vs Mazda CX-5 vs Honda CR-V) showed that the report experience, not only
the data, decides whether the product is useful:

| Observation (live chat) | Effect on the user |
|---|---|
| The report opened with 9 warnings before any answer | The answer is buried; the product looks broken |
| The comparison table had 14 rows, most with one car of three filled | Nothing can be compared at a glance |
| "Mazda wins on practicality": 583 L vs 580 L boot | Trivial differences presented as reasons to buy |
| The car with the least data won (its missing criteria were dropped from its total) | Scores look illogical; trust is lost |
| A well-researched car got a worse reliability score than an unresearched one | Same |
| Ownership cost of €513,672/year from a unit error, while the text said "no cost data" | Text and numbers contradict each other |
| Generic sentences ("for drivers who value comfort"); no engineering, depreciation or manufacturer facts | The report is boring and adds nothing the user does not know |
| "Bad, fill in everything for the Mazda" was answered with an apology | The hub does not act on critique |
| The profile was guessed once and never asked or shown | The report is not about this user |

Several of these were fixed as defects after 003 (unit normalisation, capped reliability penalties,
ranking only on criteria every car has, ties, "find it and update" requests). This feature redesigns how a
report is chosen, built, explained and discussed, so the result is personal, specific and consistent.

### How reports are built today (analysis)

1. **Compute**: deterministic scores per criterion and car, a drag-race simulation, ownership cost, and a
   fixed list of blocks ordered per persona.
2. **Write**: one AI call turns a JSON summary of the facts into free text; a number check rejects
   numbers that are not in the facts.

Weaknesses found:

- **No "what matters" step.** The AI receives all facts flat and decides what is interesting. It does not
  know which differences are meaningful (above a threshold for that attribute) or decisive for this user,
  so it writes generic text and presents noise as wins.
- **Scores are absolute indices with fixed scales** (e.g. a 0–100 km/h scale from 10 s to 3 s), which makes
  family cars all look "slow" and hides the real differences between the compared cars.
- **Gaps are reported per section** as separate warnings instead of one picture of what is known.
- **Text and blocks are produced independently**: the text can claim "no data" next to a block with data.
- **The persona only reorders blocks**; it does not change what is explained or how deep.
- **Context content is missing**: engineering differences, depreciation, manufacturer situation and
  model-year changes are either not researched or not used by the writer.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verdict first, personal and concrete (Priority: P1)

A buyer compares three cars. The first thing they see is a short verdict for them: which car fits them
best and why, the main trade-off in numbers ("the RAV4 uses 0.8 l/100 km less, about €190 a year at your
15,000 km, but costs €10,400 more than the CX-5"), how confident the verdict is and why, and what would
change it. Everything else is below, in sections they can open.

**Why this priority**: the user must get a useful answer in the first screen; today it is buried.

**Independent Test**: golden comparisons for each profile; the first block is the verdict card, it names
a winner or an explicit tie, at least one trade-off with numbers and units, a confidence level with its
reason, and nothing contradicts the blocks below.

**Acceptance Scenarios**:

1. **Given** a completed comparison, **When** the report is shown, **Then** the verdict card comes first
   with: recommendation (or "too close to call"), 2–3 reasons tied to the user's priorities, the main
   trade-off with numbers, confidence (high/medium/low) and its reason, and "what would change this".
2. **Given** a difference below the meaningful threshold for its attribute (e.g. 3 L of boot), **When** the
   verdict and text are written, **Then** it is described as "about the same", never as an advantage.
3. **Given** the cars are within the tie margin, **When** the verdict is shown, **Then** it says they are
   close and explains what would tip the balance for this user.
4. **Given** key data is missing for one car, **When** the verdict is shown, **Then** the confidence is
   lowered and the missing data is named with a "find it" action.

---

### User Story 2 - Rich, specific content: technology, depreciation, manufacturer (Priority: P1)

The report explains the real differences: how the hybrid systems work and differ (power split vs series
hybrid, battery size, electric-only range in town), gearboxes, platforms, safety equipment; how much each
car is expected to lose in value over 3 and 5 years and why; the manufacturer's situation (market share
trend, financial health, reliability reputation, dealer and parts network in Spain); what changed between
model years; ownership cost over the years. Each fact has a source and a date; estimates are labelled.

**Why this priority**: the user called the report "boring"; specific, sourced insight is the product's value.

**Independent Test**: golden comparisons of well-documented cars; each report contains at least one
sourced engineering difference, a depreciation figure or range per car (sourced or labelled estimate),
and a manufacturer section with at least two sourced facts per make, or "insufficient data" with a
"find it" action.

**Acceptance Scenarios**:

1. **Given** cars with different powertrains, **When** the report is shown, **Then** an engineering section
   explains the difference concretely (what it means for consumption, performance, reliability, cost)
   with sourced numbers.
2. **Given** depreciation data from analysts or editorial sources, **When** the report is shown, **Then** it
   gives the expected value after 3 and 5 years per car (range, source, date); without such data it shows
   the labelled estimate from the depreciation curve.
3. **Given** manufacturer facts are found, **When** the report is shown, **Then** it summarises market share
   trend, financial health, reliability reputation and service network in Spain, each with a source.
4. **Given** a model-year change matters (facelift, new engine, recall fixed), **When** the report concerns
   that model, **Then** it says what changed and from which year.

---

### User Story 3 - Report algorithms that are consistent and explainable (Priority: P1)

Before the AI writes, a deterministic step selects the meaningful differences and decisive facts for this
user (thresholds per attribute, the user's priorities, data confidence). Scores are explained relative to
the compared cars (best = reference) with the absolute values visible. The text is checked against the
blocks so it cannot contradict them (claims of "no data" where data exists, wins below the threshold,
numbers that are not in the facts).

**Why this priority**: inconsistent or illogical numbers destroy trust faster than missing data.

**Independent Test**: golden dialogues with known data: zero contradictions between text and blocks, zero
"wins" below the threshold, every number in the text traceable to a block; replaying the same data gives
the same insights.

**Acceptance Scenarios**:

1. **Given** the computed facts, **When** insights are prepared, **Then** each insight has: attribute, cars,
   difference with unit, whether it is meaningful (threshold), relevance to the user's priorities, and data
   confidence; only meaningful insights reach the writer.
2. **Given** a criterion score, **When** it is shown, **Then** the user can see the underlying values, the
   comparison basis (relative to the best car, absolute scale) and what was not compared because data was
   missing.
3. **Given** the AI text states something the blocks contradict, **When** the check runs, **Then** the text
   is corrected or regenerated before it is shown.
4. **Given** a single car (profile report), **When** it is shown, **Then** scores are absolute with the scale
   explained, and no ranking language is used.

---

### User Story 4 - Data gaps in the open, with a "find it" action (Priority: P2)

Instead of a wall of warnings, one compact "what we know" panel shows per car which areas are complete,
partial or missing, and offers "find it" for the gaps. The comparison table shows only rows that have data
for at least one car and marks gaps per cell. Pressing "find it" runs targeted research and updates the
report in place.

**Why this priority**: the user must see what is missing and be able to fix it with one action.

**Independent Test**: a comparison with known gaps shows one panel (no separate warning per section), each
gap has a "find it" action, pressing it runs research for those areas only and the report updates.

**Acceptance Scenarios**:

1. **Given** gaps in several areas, **When** the report is shown, **Then** there is one data panel at the
   bottom of the verdict (or a compact strip) instead of separate warnings, with per-car status per area.
2. **Given** the user presses "find it" for a car, **When** the research finishes, **Then** the report is
   rebuilt and the panel shows what changed ("+12 values: specs now complete").
3. **Given** a gap that research cannot close, **When** the attempt finishes, **Then** the panel says so
   with the reason (no sources, sources blocked, not sold in Spain) and does not offer the same search again
   until something changes.

---

### User Story 5 - Profile and real dialogue (Priority: P2)

The hub infers who the user is (experience, age, family, usage, budget, what matters) from what they say,
shows this profile in the case panel with the words it came from, asks 1–3 short questions only when the
answer would change the result, and adapts what the report explains and how deeply. After a report it
offers next steps as suggestions ("why?", "what if used?", "compare on reliability", "cheaper
alternative"). Critique ("bad", "incomplete", "fill in the Mazda") always leads to action: targeted
research or a reworked report, never only an apology. "This is wrong" on any value or claim leads to a
correction or a re-check of that value.

**Why this priority**: the report is only good if it is about this user; and the user must be able to steer.

**Independent Test**: dialogues where the profile is clear (no questions asked), unclear in a way that
matters (1–3 questions, then a tailored report), and critique (the report changes); "this is wrong" on a
value triggers a re-check of that value.

**Acceptance Scenarios**:

1. **Given** a first message that does not say what matters and the answer depends on it, **When** the hub
   replies, **Then** it asks at most 3 short questions (with suggested answers) before researching.
2. **Given** the profile is clear from the message, **When** the hub replies, **Then** it asks nothing and
   shows the inferred profile with its evidence.
3. **Given** a report, **When** it is shown, **Then** 3–4 next-step suggestions relevant to this comparison
   are offered as one-click actions.
4. **Given** critique of the report, **When** the user sends it, **Then** the hub states what it will do,
   does it (research or rework), and shows a changed report or explains precisely why it cannot.
5. **Given** "this is wrong" on a value, **When** the user marks it, **Then** that value is re-checked
   against its sources (and searched again if needed) and the result is shown.

---

### User Story 6 - Live research progress you can follow (Priority: P3)

While research runs, the user sees a car × area grid (found / searching / not found) with a short line of
what is happening, instead of a scrolling status feed; partial results appear as soon as they are known.

**Why this priority**: research takes minutes; the user should see progress and not think it hangs.

**Independent Test**: during a 3-car research the grid updates within seconds of each job's progress and
ends in a final state for every cell.

**Acceptance Scenarios**:

1. **Given** research is running, **When** a job starts or finishes, **Then** its cell changes state within
   5 seconds.
2. **Given** the user reloads the page during research, **When** the page is back, **Then** the grid shows
   the current state (no lost progress or questions).

---

### User Story 7 - In the user's language, on any screen (Priority: P3)

The interface (labels, buttons, blocks, panels) appears in the user's language (Russian, Spanish or
English, from the conversation or a switch), and the report is comfortable to read on a phone.

**Why this priority**: the user writes in Russian and reads labels in English today.

**Independent Test**: a Russian conversation shows the interface in Russian; on a 375 px wide screen the
verdict, table and panel are readable without horizontal scrolling.

**Acceptance Scenarios**:

1. **Given** the user writes in Russian, **When** the report is shown, **Then** all interface labels are in
   Russian; switching the language changes them immediately.
2. **Given** a phone screen, **When** the report is shown, **Then** the comparison table stacks or scrolls
   inside its block, and buttons are large enough to tap.

---

### User Story 8 - The exact cars, settled with the user before any research (Priority: P1)

Before any research starts, every car is pinned down: make, model, generation and version (engine, gearbox,
drive and equipment level). When the hub asks about a car, it checks the answer. If the answer does not
settle the question (nonsense, another topic, a model that does not exist, a version that does not fit), the
hub says what it did not understand and asks again with options. It never continues on a guess. The loop is
cheap: it uses no search and no research until the cars are settled.

When the user does not name an equipment level, the cars are compared at the **same level**: the base
version of each model (the cheapest version on sale in Spain at its official price). The report says so
("compared at base level"). When the user names a version for a car, that version is used, and the other
cars without a named version are matched at the same level (base, mid or top of their range).

**Why this priority**: research on the wrong car, or a base car against a top version, makes every number
of the report wrong; the user saw the graph start after a meaningless answer.

**Independent Test**:
- Dialogues where the user answers a model question with nonsense, an unknown model, a valid answer, and
  "choose for me". The nonsense and the unknown model are asked again. No research starts until every car
  is settled. "Choose for me" takes the base level.
- Comparisons without versions use the base version of each car. A comparison with one named version
  matches the others at its level.

**Acceptance Scenarios**:

1. **Given** a question about a car's version, **When** the user answers with text that does not identify
   it, **Then** the hub says what it did not understand and asks again (same question, with options), and
   no search or research runs.
2. **Given** a model that does not exist or is not known, **When** the user names it, **Then** the hub says
   so and offers the closest known models; it does not invent a variant.
3. **Given** several versions (engines, gearboxes, drives) and no hint, **When** the hub proposes one,
   **Then** the user confirms or picks one; research starts only after every car is confirmed or uniquely
   determined.
4. **Given** no equipment level named for any car, **When** the cars are identified, **Then** each car is
   the base version on sale (cheapest official price), and the verdict and case panel say "compared at
   base level".
5. **Given** a named version for one car (e.g. "CX-5 Homura"), **When** the others have none, **Then** they
   are matched at the same level of their range (top, mid or base) and the report names each version.
6. **Given** the user says "any" or "choose for me", **When** the hub applies it, **Then** it takes the base
   level and says which version it took.

### Edge Cases

- Only one car: a profile report (absolute scores, no winner), with the same verdict-first layout.
- Very different cars (city car vs large SUV): the verdict says they serve different needs and asks what
  matters if the profile does not tell.
- All key data missing for every car: the verdict is "not enough data to recommend", with "find it" actions,
  not a confident pick.
- Conflicting sources on a decisive value: the verdict names the conflict and lowers confidence.
- The user's critique is vague ("this is rubbish"): the hub asks one question about what to improve while
  starting the most likely action (research of the biggest gaps).
- Depreciation or manufacturer data only from one market (e.g. UK): shown with the market named.
- The user switches language mid-chat: interface and replies follow the latest message.
- The user keeps giving answers that do not settle a car: the hub keeps asking (each time with fewer,
  clearer options plus "choose for me" and "remove this car"); it never researches a guessed car.
- The base version is not sold with the gearbox or drive the user wants (e.g. AWD only on mid trims): the
  lowest level with that gearbox or drive is taken and the report says so.
- Official prices per version are not found: the level is taken from the manufacturer's range order (first
  listed = base) and labelled as such.

## Requirements *(mandatory)*

### Functional Requirements

**Verdict and structure (US1)**

- **FR-001**: Every comparison report MUST start with a verdict card: recommendation or explicit tie,
  2–3 reasons linked to the user's priorities, the main trade-off expressed with numbers and units,
  confidence (high/medium/low) with its reason, and what would change the verdict.
- **FR-002**: Details MUST follow in sections the user can expand or collapse; the order and which
  sections are open by default depend on the profile.
- **FR-003**: A difference MUST be called an advantage only when it exceeds the configured meaningful
  threshold for that attribute (e.g. boot volume, consumption, acceleration, price, cost per year);
  smaller differences MUST be described as about the same.

**Rich content (US2)**

- **FR-004**: The report MUST include an engineering section that explains the meaningful technical
  differences (powertrain and hybrid system, gearbox, platform, battery, safety equipment) and what they
  mean for consumption, performance, reliability and cost, with sourced values.
- **FR-005**: The report MUST include expected value retention after 3 and 5 years per car: a sourced
  range (analysts, editorial sources; source, market and date shown) or the labelled depreciation estimate.
- **FR-006**: The report MUST include a manufacturer section per make: market share trend, financial
  health, reliability reputation and service network in Spain, each with a source and date, or
  "insufficient data" with a "find it" action.
- **FR-007**: The report MUST mention model-year changes relevant to the compared cars (facelift, engine
  change, recall fixed) when sourced.
- **FR-008**: The report MUST show ownership cost over time (per year and over 5 years) with its parts and
  assumptions.

**Report algorithms (US3)**

- **FR-009**: Before any text is written, a deterministic step MUST produce the list of insights: attribute,
  cars, difference with unit, meaningful or not (threshold), relevance to the user's priorities, and data
  confidence; the writer receives the meaningful, relevant insights first.
- **FR-010**: Criterion scores MUST be shown with their basis: underlying values, comparison relative to
  the best of the compared cars, the absolute scale, and the criteria not compared because of missing data.
- **FR-011**: The ranking MUST use only criteria every compared car has data for; totals within the tie
  margin MUST be reported as a tie (as fixed after 003, kept as a requirement).
- **FR-012**: The text MUST be checked against the blocks before it is shown: no number that is not in the
  facts, no "no data" where a block has data, no advantage below the threshold, no winner when the result
  is a tie. Violations MUST be corrected or the text regenerated.
- **FR-013**: Given the same data and profile, the verdict, insights and block selection MUST be the same.

**Data gaps (US4)**

- **FR-014**: Gaps MUST be shown in one compact data panel (per car × area: complete, partial, missing,
  with reasons) instead of separate warnings per section.
- **FR-015**: Each gap MUST offer a "find it" action that runs targeted research for those areas and
  rebuilds the report; the panel MUST show what changed after the research.
- **FR-016**: The comparison table MUST show only rows with data for at least one car and mark missing
  cells, with "find it" on a car's column header.

**Profile and dialogue (US5)**

- **FR-017**: The profile (experience, age band, family, usage, budget, priorities) MUST be inferred only
  from the user's words (shown as evidence) and shown in the case panel; the user can edit it.
- **FR-018**: The hub MUST ask 1–3 short questions with suggested answers when the profile or a constraint
  is unknown and would change the answer, and none when it would not.
- **FR-019**: The profile MUST change the content of the report (what is explained and how deeply,
  which sections are open), not only the order of blocks.
- **FR-020**: After each report the hub MUST offer 3–4 next-step suggestions relevant to the comparison as
  one-click actions.
- **FR-021**: Critique of a report MUST lead to an action: targeted research of the gaps it names (or of the
  biggest gaps), or a reworked report with a different emphasis; the reply MUST say what was done and show
  what changed. A reply that only apologises is not allowed.
- **FR-022**: "This is wrong" on a value or claim MUST trigger a re-check of that value against its sources
  (and a new search when needed); the result (confirmed, corrected, removed) MUST be shown.

**Progress, language, layout (US6, US7)**

- **FR-023**: During research the interface MUST show a car × area progress grid that updates within 5
  seconds and survives a reload.
- **FR-024**: All interface text MUST be available in Russian, Spanish and English, following the
  conversation's language with a manual switch.
- **FR-025**: The report MUST be readable on a 375 px wide screen without page-level horizontal scrolling.

**Value sense and identity (added at planning, from the 2026-11-02 defects)**

- **FR-027**: Every value MUST pass a sense check for its attribute before it is used, not only an excerpt
  check: unit and magnitude (a service interval of 16 km or 5 months next to "years"), meaning (a hybrid
  e-CVT is not a "one-speed gearbox"), consistency with the car (power vs mass vs acceleration) and with the
  computed results (a yearly cost far outside the class range). Values failing it are rejected or flagged,
  never shown as facts.
- **FR-028**: When a model is sold with several gearboxes or driven wheels, the identified variant MUST carry
  them, and values from another gearbox or drive MUST NOT be mixed into it (e.g. manual and automatic CX-5).

**Exact identity and equal level (US8, added after tasks on user request)**

- **FR-029**: When the user names no version, all compared cars MUST be identified at the same equipment
  level: the base version on sale (cheapest official price, or first in the manufacturer's range when prices
  are not found). When the user names a version for one car, the others MUST be matched at the same level
  of their range. The level and each version MUST be shown in the case panel and the verdict.
- **FR-030**: Research MUST NOT start until every car is settled: make, model, generation and version
  (engine, gearbox, drive, equipment level) confirmed by the user or uniquely determined from the catalog.
- **FR-031**: Every answer to an identification question MUST be checked for whether it settles the
  question. An answer that does not settle it MUST lead to the same question again (what was not
  understood, the options, "choose for me", "remove this car"). The question MUST NOT count as answered, and
  no search or research MUST run.

**Research speed and verification fixes (user reports 2026-11-02)**

- **FR-032**: Each page of a research job MUST be processed as its own concurrent pipeline (relevance →
  reading or extraction → validation → storage), with model calls bounded per job and in total (config).
- **FR-033**: Consumption MUST be kept per test cycle (WLTP official, NEDC old cycle, real-world). Only
  WLTP is compared between cars. The fuel bill MUST use the real-world figure, or WLTP × a labelled
  real-use allowance. A manufacturer's WLTP range gives its upper bound. (Prado: 7.4 NEDC was shown as
  comparable with the Tucson's 6.8 WLTP.)
- **FR-034**: Excerpt checks MUST ignore markdown markup and accept an ellipsis between quoted parts.
  Official prices count only from Spanish (or market-neutral) sources, and service schedules only from
  European ones. The service interval MUST be taken from the normal schedule when no single value is
  stated. (Tucson: the price in bold was rejected, and a Malaysian 6-month schedule was used.)

**Measurement**

- **FR-026**: The user MUST be able to rate each report (1–5) and say what was missing; ratings MUST be
  stored with the report for evaluation.

### Key Entities

- **Verdict**: recommendation or tie, reasons, trade-off (insight references), confidence and its reason,
  what would change it.
- **Insight**: attribute, cars, values and difference with unit, meaningful threshold, relevance to the
  user's priorities, data confidence, source references.
- **Meaningful threshold**: per attribute, the smallest difference worth mentioning (configurable).
- **Data panel entry**: car × area status (complete, partial, missing), reason, last attempt, "find it".
- **Profile**: experience, age band, family, usage, budget, priorities, each with the words it came from.
- **Suggestion**: a one-click next step with the request it sends.
- **Equipment level**: base, mid or top position of a version in its model's range, with its official
  price when known.
- **Value challenge**: a user's "this is wrong" on a value or claim, and its outcome.
- **Report rating**: 1–5 and a free-text note per report.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users rate reports at least 4 of 5 on average in a check with at least 3 people and 10
  comparisons (baseline: the 2026-11-02 report was judged "boring" and "illogical").
- **SC-002**: In golden comparisons, 100% of verdicts name a recommendation or an explicit tie, at least one
  trade-off with numbers and units, and a confidence with its reason.
- **SC-003**: Zero contradictions between text and blocks and zero "advantages" below the threshold in the
  golden comparisons.
- **SC-004**: At least 80% of golden comparisons of well-documented cars include a sourced engineering
  difference, a value-retention figure per car (sourced or labelled), and manufacturer facts per make.
- **SC-005**: 100% of critique turns in golden dialogues lead to research or a changed report; none is
  answered with an apology only.
- **SC-006**: New chats ask 1–3 questions when the profile matters and is unknown, and 0 when it is clear
  (golden dialogues covering both).
- **SC-007**: The first useful answer (verdict card) appears within 30 seconds when the data is cached,
  and research progress is visible within 5 seconds of starting.
- **SC-008**: A report has no more than one data-quality element at the top level (no wall of warnings).
- **SC-010**: Zero values in golden comparisons that fail the sense check (the 2026-11-02 defect list is a
  regression set: 16 km intervals, years as months, one-speed e-CVT, yearly costs outside the class range).
- **SC-011**: In golden dialogues, 0 research runs start with an unsettled car, and 100% of answers that do
  not settle a car question are asked again.
- **SC-012**: In comparisons without named versions, 100% of cars are compared at the base level, and the
  report says so.
- **SC-009**: The interface in a Russian conversation shows no English labels; the report passes a 375 px
  layout check.

## Assumptions

- The data and search pipeline of 003 stays; this feature may add research areas for depreciation and
  manufacturer situation using the configured favourite sources (no new provider).
- Meaningful thresholds start from common-sense values per attribute (e.g. boot 30 L, consumption
  0.5 l/100 km, 0–100 km/h 0.5 s, price 5%, yearly cost €150) and are configuration.
- Confidence comes from data coverage and source agreement for the decisive insights.
- Ratings are collected in the product (1–5 plus a note); the usability check with people is run by the
  user.
- The model provider is whatever is configured (Gemini now); quality depends on having a paid tier.
- Out of scope: accounts and payments, new data providers beyond configuration, report export.
