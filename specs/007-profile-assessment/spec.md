# Feature Specification: The User's Profile Drives the Assessment

**Feature Branch**: `007-profile-assessment`

**Created**: 2026-11-03

**Status**: Draft

**Input**: The owner's critique of 2026-11-03 and the second part of code review 2026-11-03 (sections "Understanding the request and the profile", "Graph", "Validation", "UX", "Security", "Tests").

Owner's words: "из моего запроса не выводится мой профиль. если не понимает, то и не переспрашивает. а профиль — кто я: гонщик, эксперт или домашний папа; и сколько буду владеть; и смотрю новую или б/у; и сколько в год ездить и сколько тратить. при смене профиля вручную должны ползунки критериев меняться и тоже учитываться перед запросом. и результаты интерпретироваться под профиль… при подведении итогов и оценках это должно учитываться. в последнем запросе про немецкие авто не мог что-то найти… источник можно дополнять, если поиск дал источник. частые встречаемые источники должны храниться наряду с постоянными. кеш тоже проверь."

## Background: what went wrong on 2026-11-03 (chat 757cff3d)

The user compared a **BMW 320d Touring M Sport** with a **VW Golf Variant R**.

1. **The profile stayed empty.** After three turns the persona was "unknown". Priorities, usage, budget, km per year and "new or used" were all empty. "M Sport vs Golf R" clearly signals interest in driving, but nothing was inferred and nothing was asked. The profile has no ownership-period field at all.
2. **The profile barely changes the scores.** The weights are the persona defaults plus explicit priorities (`criteria.weights_for`). Age, family, driving style, region, climate and km per year do not change them. Manual weights set `weights_overridden=True` forever, after which persona and profile changes are silently ignored. Edits in the panel apply "from the next turn".
3. **The verdict is the same for everyone.** The same pair gets the same winner for a racer, a family that keeps cars 8 years, and a buyer of a 3-year-old used car.
4. **German cars were not found, and the cause was ours.**
   - Round-0 favourite queries carried the full variant name and the generation code ("Volkswagen Golf Mk8.5 Golf Variant R 2.0 TSI 333 CV DSG 4MOTION site:…"), so they returned nothing. pages_found was 0 for specs, reliability, measured and manufacturer.
   - English words ("reliability problems") went to Spanish sites.
   - 118 of 439 cached searches were empty (117 of them `site:` queries), and an empty answer was cached for the full TTL.
   - Sources that searches keep finding are never kept.
   - The cache itself works: 82 of 376 searches came from the cache.
5. **Intake mistakes.** The user picked an option the bot had offered ("320d Touring M Sport"), and the bot answered "there is no such engine". For a new car it chose the old generation (F30) instead of the current one (G20).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The profile is understood, and asked when it matters (Priority: P1)

From the first message the system infers who the user is and how they will use the car. The profile has these parts:

- **Persona**: racer or enthusiast, expert, family driver or practical buyer.
- **Ownership period**: years.
- **New or used**, and the age of a used car.
- **Distance**: km per year.
- **Money**: purchase budget and/or monthly spending limit.
- **Optional**: family, driving style, region, climate.

Each field is marked **stated**, **inferred** (with the words it came from) or **assumed** (a default). When a missing or uncertain field would change the answer, the system asks **one** short question with chip answers. Otherwise it goes ahead and says what it assumed.

**Why this priority**: every other story depends on a profile that exists. Today it is empty.

**Independent Test**: "BMW 320d M Sport или Golf R?" gives the persona "enthusiast", marked inferred and citing the words "M Sport", "Golf R". The ownership period and km are assumed defaults, each marked. No more than one question is asked before research.

**Acceptance Scenarios**:

1. **Given** "вожу детей в школу, по выходным в горы", **When** it is interpreted, **Then** family is FAMILY (inferred) and usage includes mountains. The confirmation card shows both with a "correct?" chip.
2. **Given** a message without km or ownership period, **When** scoring with 2–3 plausible values of the field gives the same winner and the same tie status, **Then** no question is asked and the default is shown as "assumed". **When** the winner or the tie changes, **Then** the question is asked, with chips for those values.
3. **Given** a field the user stated, **When** a later message implies otherwise, **Then** the stated value is kept until the user changes it explicitly.
4. **Given** the budget written "20к", "до 20 тыщ", "25.000 €" or "1,5 млн", **When** it is interpreted, **Then** the amount is 20,000, 20,000, 25,000 or 1,500,000.
5. **Given** "Golf 7 2015", **When** numbers are read, **Then** they are 7 and 2015, never 72015.

---

### User Story 2 — The profile changes the weights, visibly (Priority: P1)

The criteria weights are a pure function of the persona defaults, the profile rules, the priorities and the user's manual adjustments. The result is normalised to 100. The profile rules live in a YAML file, not in code. Every weight shows where it came from, for example "+10 % practicality — family" or "+8 % efficiency — 30,000 km a year".

Manual changes are adjustments on top of the automatic weights. They do not freeze the weights. They carry a "set manually" badge and a "back to automatic" button.

**Why this priority**: the owner's main complaint. Without it the profile is decoration.

**Independent Test**: "family + mountains + calm" and "single + city + sporty" with the same persona give different weights, and every difference has a stated reason. A manual adjustment survives a later change of persona; the other weights still follow the new persona.

**Acceptance Scenarios**:

1. **Given** the rules file, **When** a profile field changes, **Then** the weights change by the rule for that field, and the card lists each reason.
2. **Given** manual weights, **When** the persona changes, **Then** the manual adjustments are kept on top of the new persona's defaults. Nothing is silently ignored.
3. **Given** "back to automatic", **When** it is pressed, **Then** the adjustments are removed and the automatic weights are shown.
4. **Given** km per year above 25,000 and an ownership period of 8 years or more, **When** the weights are computed, **Then** efficiency and ownership cost gain weight, with those reasons.

---

### User Story 3 — A change in the panel recalculates at once (Priority: P1)

The panel edits the whole profile, not only the weights:

- persona;
- ownership period;
- new or used;
- km per year;
- budget;
- family;
- driving style;
- region;
- usage.

A change takes effect immediately. If only the assessment parameters changed and the car data is fresh, the system recalculates without research and without the interpreter. The recalculation covers the criteria, the ownership cost, the verdict and the insights. It then writes a short "what changed" text. Changed scores are highlighted. If the change needs new data (for example a used car instead of a new one), the system says so and offers a research run.

A change made before research (on the confirmation card) is used by that research. Example: the areas researched and their depth follow the persona.

**Why this priority**: the owner asked for the sliders to change with the profile and be used before the request. Today a change waits for the next message.

**Independent Test**: in a finished report, switching the persona from "family" to "enthusiast" changes the weights, the scores and, where the data supports it, the winner. This takes under 2 seconds and makes no web search and no interpreter call.

**Acceptance Scenarios**:

1. **Given** a finished report, **When** the user changes km per year in the panel, **Then** the ownership cost, the break-even and the verdict are recalculated. The text says what changed and why.
2. **Given** a change that only the assessment uses, **When** the next decision is taken, **Then** the policy chooses RESCORE, not research and not "nothing new".
3. **Given** a change to "used, 3 years old", **When** it is applied, **Then** the system states which data is missing for used cars and offers research. It does not pretend the new-car data fits.
4. **Given** the persona changed on the confirmation card, **When** research starts, **Then** the plan uses the new persona's areas.

---

### User Story 4 — The verdict and the text speak to this user (Priority: P1)

The verdict, the scores, the ownership cost and the insights are computed by code for this profile:

- **Ownership period**: depreciation and total cost over that period.
- **Distance**: energy and maintenance at that km.
- **New or used**: purchase price of that kind.
- **Budget**: over budget is a stated finding, not a silent drop.

The text is written for the persona. It explains why the winner wins for this user, and when a different user would choose differently.

**Why this priority**: the owner's "results interpreted for the profile". This is what makes the advice personal.

**Independent Test**: one pair with three profiles gives three reports, and each explains its verdict by the profile. The profiles are: racer, 3 years; family, 8 years and 20,000 km; used buyer, 5,000 €/year limit. At least two of the three verdicts differ, where the data supports it.

**Acceptance Scenarios**:

1. **Given** an ownership period of N years, **When** the ownership cost is computed, **Then** it covers N years (depreciation to year N, energy, maintenance, insurance and tax). The period is shown.
2. **Given** a monthly spending limit, **When** a car's monthly cost exceeds it, **Then** the report says so with the numbers, and the verdict takes it into account.
3. **Given** the persona "enthusiast", **When** the verdict is written, **Then** it leads with driving criteria. **Given** "family", **Then** it leads with space, safety and cost. Both come from the same computed facts.
4. **Given** a close result, **When** the insights are built, **Then** they include "if you keep the car more than N years / drive more than X km, Y wins". This exists today and now uses the user's numbers.

---

### User Story 5 — Searches find what exists, and good sources are remembered (Priority: P1)

Round-0 favourite queries are short and in the language of the market. They name the make, the model and a short variant key such as "320d" or "Golf R". They never include generation codes, duplicated words or gearbox noise.

When a favourite query returns nothing, a shorter query is tried once. An empty search result is cached for hours, not for the full TTL.

Domains that repeatedly give accepted values are stored as **learned sources**, next to the configured ones. Each records its area, market, source type, count of accepted values and when it was last seen. Learned sources join round 0 after the configured ones. They expire when they stop giving values. A learned source never gets MANUFACTURER authority, and deny-listed sites never become learned sources.

**Why this priority**: without data the profile work has nothing to assess. The German-car chat shows the search, not the web, was the problem.

**Independent Test**: re-run the research of chat 757cff3d (BMW 320d Touring G21 vs Golf Variant R). Round 0 finds pages for specs, measured and reliability for both cars. No query contains "Mk8.5" or a duplicated model name.

**Acceptance Scenarios**:

1. **Given** a variant "Volkswagen Golf Mk8.5 Golf Variant R 2.0 TSI 333 CV DSG 4MOTION", **When** the favourite query is built, **Then** it is short, for example "Volkswagen Golf Variant R 333", and has no generation code and no repeated model name.
2. **Given** a German favourite site, **When** a reliability query is built, **Then** it uses German words ("Pannenstatistik", "Mängel"). **Given** a Spanish site, **Then** it uses Spanish words ("fiabilidad", "problemas").
3. **Given** a favourite query with zero results, **When** round 0 continues, **Then** one shorter query is tried. The empty answer is cached for a short time (6 hours by default).
4. **Given** a domain that gave accepted values in 3 or more research runs, **When** sources are updated, **Then** it becomes a learned source for that area and market. It is listed on the metrics page.
5. **Given** a learned source with no accepted value in its last N uses, **When** sources are updated, **Then** it expires.

---

### User Story 6 — Intake does not contradict itself (Priority: P2)

An option the system offered is always accepted when the user picks it. For a new car the current generation is chosen unless the user names another.

**Why this priority**: a small but trust-breaking defect seen live.

**Independent Test**: replay chat 757cff3d. Picking "320d Touring M Sport" is accepted, and the generation is G21 (current Touring), not F30/F31.

**Acceptance Scenarios**:

1. **Given** an option offered by the line-up, **When** the user picks it (by chip or by its text), **Then** it is resolved to exactly that option, and no "no such engine" answer is possible.
2. **Given** intent "new" or unknown and no year, **When** the generation is chosen, **Then** it is the one currently sold. An old generation is chosen only when the user says used or names a year or code.

---

### User Story 7 — Advice without named cars (Priority: P3)

"Посоветуй семейный кроссовер до 25к" no longer gets a general text. The system builds a case: profile and budget → 2–3 candidates from the line-up mechanism → confirmation → the usual research.

**Why this priority**: valuable, but it depends on US1–US4.

**Independent Test**: that message gives a confirmation card with 2–3 candidate cars within the budget, each with a one-line reason.

**Acceptance Scenarios**:

1. **Given** a request with a class, a budget and no named car, **When** policy decides, **Then** it chooses candidate selection, not a general answer.
2. **Given** candidates, **When** the user removes or adds one, **Then** research runs on the confirmed list.

---

### Edge Cases

- The user contradicts an inferred field ("я не семейный"): it becomes stated, and the inference is never repeated.
- A profile change during a running research is queued and applied when the run ends (one turn per chat stays the rule).
- Every field is unknown and the answer does not depend on them: no question; all assumptions are listed.
- The rules push one criterion above 50 %: weights are capped and normalised, and the cap is shown.
- Manual weight 0 for a criterion: the criterion is excluded and shown as "excluded by you".
- A learned source that becomes deny-listed is removed at once.
- A learned source of a brand look-alike domain (for example "bmw-club.es") is never MANUFACTURER.
- A recalculation (RESCORE) on stale data: the system says the data is older than its TTL and offers a refresh.

## Requirements *(mandatory)*

### Functional Requirements

**Profile model and inference**

- **FR-001**: The profile MUST contain:
  - persona;
  - ownership_years;
  - new_or_used, plus the age of a used car;
  - annual_km (a range is allowed);
  - purchase budget;
  - monthly spending limit;
  - family;
  - driving_style;
  - region and climate;
  - usage.

  Each field MUST carry a status: stated, inferred or assumed. A stated or inferred field also carries the words it came from.
- **FR-002**: The interpreter MUST be allowed to infer profile fields from the whole dialogue, each with the words it relied on. Today it may only set fields the latest message states. An inferred field never overrides a stated one.
- **FR-003**: Defaults for assumed fields MUST come from configuration, per persona. Examples: ownership 5 years, 15,000 km a year, new.
- **FR-004**: The number reader MUST handle "к", "тыс", "тыщ", "млн", "k" and "mil", and thousand separators in ru/es/en. It MUST NOT join numbers separated by a space unless they form a thousands group ("Golf 7 2015" → 7, 2015).
- **FR-005**: The interpreter MUST see enough dialogue to infer the profile. The window grows from 12 turns × 500 characters to a budget set in configuration, with a summary of older turns.

**Questions by value**

- **FR-006**: Before research, the system MUST ask about a missing or uncertain field only when scoring with 2–3 plausible values of that field changes the winner or the tie status. It MUST ask at most one profile question per turn, with chip answers.
- **FR-007**: `full_intake` MUST default to false. The total intake path before the first research MUST be no longer than two questions.

**Weights**

- **FR-008**: Weights MUST be computed by a pure domain function: persona defaults + `profile_rules.yaml` + priorities + manual adjustments, then capped and normalised to 100. Each contribution MUST record its reason.
- **FR-009**: The rules MUST cover at least:
  - family;
  - driving style;
  - usage (city, motorway, mountains, towing);
  - climate;
  - km per year;
  - ownership period;
  - new or used.
- **FR-010**: Manual weights MUST be stored as adjustments, not as a frozen set. "Back to automatic" MUST remove them. A persona change MUST keep the adjustments and recompute the rest.
- **FR-011**: The criteria card MUST show each weight's reasons and a "set manually" badge where one applies.

**Recalculation (RESCORE)**

- **FR-012**: The case fingerprint MUST have two parts: car data (variants, values, data version) and assessment parameters (profile, weights, priorities, region, language). The policy MUST choose RESCORE when only the assessment part changed and the data is fresh, research when the data part changed or is stale, and "nothing new" only when neither changed.
- **FR-013**: RESCORE MUST recompute the criteria, the ownership cost, the verdict and the insights by code, without web search and without the interpreter. It ends with one short "what changed" text over the facts. Changed scores MUST be highlighted in the UI.
- **FR-014**: A panel edit MUST trigger RESCORE at once, without waiting for a message. The panel MUST edit every profile field in FR-001.
- **FR-015**: Profile changes made on the confirmation card MUST be applied before research starts and MUST shape the research plan. The persona decides the areas and their depth.

**Assessment by profile**

- **FR-016**: The ownership cost MUST cover the user's ownership period and km per year. It MUST include depreciation to that year and show the period.
- **FR-017**: A car whose purchase price exceeds the budget, or whose monthly cost exceeds the spending limit, MUST get a stated finding with the numbers. The verdict MUST take it into account by a documented rule.
- **FR-018**: The verdict and the insights MUST use the profile's numbers. The report text MUST lead with the criteria the persona weights highest. It MUST state when another profile would choose differently, by a code-computed counterfactual: same data, different persona.
- **FR-019**: For "used" the system MUST say which data it lacks for a used car (age-specific price, wear) and MUST NOT present new-car prices as used prices. Full used-car mode stays a later spec.

**Search recall and learned sources**

- **FR-020**: Favourite (round-0) queries MUST use a short identity:
  - make, model and a short variant key (engine code such as "320d", or the named trim such as "R" or "GTI");
  - no generation codes, no repeated words, no gearbox or drive noise;
  - the area words in the market's language.
- **FR-021**: A favourite query with zero results MUST be retried once with a shorter form. Empty search results MUST be cached with a short TTL (default 6 hours), separate from the area TTL.
- **FR-022**: A domain whose values were accepted in at least K research runs (default 3) MUST be stored as a learned source with these fields:
  - area;
  - market;
  - source type (classified by the usual rules, never MANUFACTURER unless official);
  - count;
  - first and last seen.

  Learned sources MUST be used in round 0 after configured favourites. They MUST expire after M uses without an accepted value. Deny-listed domains MUST never be learned.
- **FR-023**: The metrics page MUST list the learned sources and the share of empty searches per area and market.

**Intake fixes**

- **FR-024**: A choice among offered options MUST resolve to that option without re-validation against the user's earlier text.
- **FR-025**: For a new or unknown intent without a year, the generation MUST be the one currently sold.

**Advice without cars**

- **FR-026**: A request with a class or need and a budget, but no named car, MUST start candidate selection: 2–3 candidates with reasons, then confirmation, then research.

**Graph robustness (from the review, needed by RESCORE)**

- **FR-027**: The graph MUST keep a hop counter in state and leave a loop gracefully with a partial answer.
- **FR-028**: LLM nodes MUST retry transient provider errors with a policy, and fall back to a plain localized message.
- **FR-029**: On a turn timeout the user MUST get the result built from data already collected, not only "took too long".

**Validation gaps (from the review, still open)**

- **FR-030**: An ellipsis in an excerpt MUST NOT skip more than about 200 characters of the document.
- **FR-031**: A value MUST be found in the excerpt at number boundaries. "150" MUST NOT match inside "1500 rpm".
- **FR-032**: Text attributes (gearbox, body, fuel) MUST be compared for agreement, not always "agree".
- **FR-033**: The number guard MUST NOT let every integer ≤ 12 and every year 1950–2035 through. Small integers and years are allowed only when they appear in the facts.
- **FR-034**: The report check MUST match words at word boundaries. "más" MUST NOT match inside "además", and "more" MUST NOT match inside "moreover".

### Key Entities

- **Profile field**: a value, a status (stated, inferred or assumed) and the words it came from.
- **Profile rule**: a field and a value mapped to weight changes per criterion, with a reason text.
- **Weight breakdown**: per criterion, the persona base, the rule contributions with reasons, the manual adjustment, and the final normalised weight.
- **Assessment fingerprint**: a data part and a parameters part.
- **Learned source**: domain, area, market, source type, accepted count, uses since the last accepted value, first seen and last seen.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the golden set, 100 % of first messages that signal a persona ("M Sport", "дети", "трек", "экономно") get it inferred, with the words it came from.
- **SC-002**: No more than one profile question is asked before the first research in every golden dialogue. A question is asked only when it changes the winner or the tie (checked by the test harness).
- **SC-003**: Two profiles that differ only in family, usage, style, km or ownership period give different weights, each difference with a reason. This is a unit test per rule.
- **SC-004**: A panel change of persona, km, ownership period or budget updates the report in under 2 seconds, with zero web searches and zero interpreter calls.
- **SC-005**: For the three-profile pair test (US4), at least two verdicts differ, and each verdict text names the profile reason.
- **SC-006**: Re-running chat 757cff3d finds round-0 pages for specs, measured and reliability for both cars. The share of empty favourite searches drops below 25 % (it was 27 % overall, and 0 hits for these areas).
- **SC-007**: After 10 research runs on German and Spanish cars, at least 3 learned sources exist, none is MANUFACTURER or deny-listed, and each has at least 3 accepted values.
- **SC-008**: Replaying chat 757cff3d, the offered option is accepted, and the generation is the current one.
- **SC-009**: The regression tests for FR-030 to FR-034 pass, each with the example from the review.

## Assumptions

- Personas stay EXPERT, PERFORMANCE, BUYER and UNKNOWN in code. "Racer or enthusiast" maps to PERFORMANCE and "family driver" to BUYER with family. The user-facing names are localized labels.
- The profile rules start from the review's example and are tuned on the golden set. The numbers are configuration, not code.
- Ownership-period depreciation uses the existing value-retention data. Where it is missing, the report says so; it is never invented.
- RESCORE reuses the existing compute and preset path. It is a new policy action, not a new graph.
- Learned sources live in the database, not in sources.yaml. The YAML stays the configured list under review.
- Security items from the review must be done before any external demo, but are out of scope here:
  - SSRF checks on user URLs;
  - chat isolation by token;
  - closed metrics;
  - a WebSocket Origin check;
  - a daily budget cap;
  - logging the real model.

  They are listed in docs/review-2026-11-03.md.
- Spec 006 (electrified cars) is independent. Its energy cost plugs into the same ownership-cost period (FR-016).

## Out of Scope

- Full used-car mode: archive prices, wear and history.
- JS rendering and JSON-LD readers.
- Splitting research.py and compose.py, and a confirm subgraph (review backlog, refactor plan).
- Security hardening for an external demo (see Assumptions).
- LangGraph Studio and a turn trace CLI (backlog).
