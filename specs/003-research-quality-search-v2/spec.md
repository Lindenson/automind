# Feature Specification: Research Quality and Search v2

**Feature Branch**: `003-research-quality-search-v2`

**Created**: 2026-11-02

**Status**: Draft

**Input**: User description: "003 — Research quality and search v2 (data quality first). Replace the current
general-purpose AI search as the primary search with a Google results provider behind a provider-agnostic
search interface; own page fetching and parsing with deterministic parsers for favourite spec sites;
favourite sources per research area and market in configuration; relevance and validation of every page
and value against the exact variant and against what the user asked; feasibility check of the user's
budget, running-cost and usage constraints with an explicit verdict or a clarifying question; storage
completed in one PostgreSQL for development and deployment, with migration of existing data and a
search/page cache; deletion of old chats. Out of scope: model provider change, UI redesign, external
access for desktop AI clients, secondary-market prices."

## Context and Problem

Spec 002 (conversational MVP) is implemented. Live use shows that the biggest damage is not the
conversation but the data: poor source selection and low-quality values. Measured on the development
database before this feature:

| Observation | Value |
|---|---|
| Search and page-extraction spend vs. all AI model spend | ≈ €1.52 vs ≈ €0.55 |
| Instrumented-test (measured 0–100) research tasks that found nothing | 7 of 12 |
| Official-price research tasks that found nothing | 4 of 7 |
| Reliability statements rejected vs. accepted | 39 vs. 33 |
| Reports with "insufficient data" for cars that are well documented online | frequent (e.g. BMW 520d G30) |

The search returns generic pages, misses the specialised sites that hold the needed numbers, pays
again for the same queries, and leaves the AI to read long pages that a simple table reader could
read exactly. Values from the wrong generation or engine still reach the validation step, and the
validation compares a value with its page but not with what the user asked. When the user's budget
or usage makes the request impossible (or possible only as a used car), the hub still writes a
report instead of saying so.

## Clarifications

### Session 2026-11-02

- Q (user, during implementation): limits cut research short — what should happen instead?
  → A: ask the user to continue or answer with what exists; never cancel (FR-032).

- Q: Secondary-market prices are out of scope; how is the used-car age range for a budget estimated?
  → A: Base estimate from the official new price × configured depreciation curve (labelled
  assumption), refined by used-price ranges quoted in editorial sources (not classifieds); editorial
  range wins when they disagree; both shown.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reliable data for the exact car (Priority: P1)

A user compares two cars. The research looks first at the sites that are known to hold each kind of
data (specification databases, instrumented road tests, manufacturer price lists, reliability
surveys, owner reviews) in the right market and language, reads specification tables exactly, rejects
pages about another generation, engine or body with a stated reason, and checks every value for
plausibility and agreement between sources. The report shows real numbers with their sources where
the data exists online, and "insufficient data" only where it really does not.

**Why this priority**: wrong or missing numbers make every report useless; this is the main
complaint from live use.

**Independent Test**: run new research for a benchmark list of well-documented cars (including
known generation traps such as Prado J150/J250, Golf Mk7/Mk8, BMW 3 Series F30/G20, E-Class
W212/W213) and check the share of sections that meet their minimum evidence, the values against
reference data, and that no value from a wrong variant is shown.

**Acceptance Scenarios**:

1. **Given** a confirmed BMW 5 Series G30 520d and empty cache, **When** research runs, **Then**
   power, torque, mass, dimensions, boot volume and consumption come from at least one favourite
   specification source read without AI, agree with a second independent source, and the
   specification section meets its minimum.
2. **Given** a confirmed Toyota Land Cruiser Prado J150, **When** a found page describes the J250,
   **Then** the page is rejected before any value is extracted, and the rejection reason
   ("other generation: J250, 2024–") is recorded and visible in the source list.
3. **Given** a value outside the plausible range for its attribute and class (e.g. 0–100 km/h in
   1.9 s for a diesel saloon, curb mass 150 kg), **When** it is extracted, **Then** it is rejected
   as implausible and does not reach the report.
4. **Given** two sources that disagree beyond the tolerance for an attribute, **When** values are
   selected, **Then** the existing conflict rules apply and the report shows the conflict instead of
   silently picking one.
5. **Given** the specialised sources do not meet a section minimum, **When** the research round
   ends, **Then** an open-web search is used for that section only, and if the minimum is still not
   met the section is marked "insufficient data" with what was tried.
6. **Given** the user asked about a specific market, body, engine or year, **When** values are
   validated, **Then** the validator checks them against the user's case (requested variant,
   market, condition, year) and not only against the page text.

---

### User Story 2 - Search that costs less and is not paid twice (Priority: P1)

The operator configures the search provider (a Google results provider by default) and the favourite
sources. The hub builds the search queries itself, queries favourite sites first, fetches and reads
pages itself (respecting robots directives, the deny-list and rate limits), and reuses search results
and fetched pages it already has. A bounded extra round of AI-proposed queries is allowed only for
sections still below their minimum and only within the turn budget.

**Why this priority**: search is now the largest cost while returning little; the same budget must
buy more validated data.

**Independent Test**: run the same benchmark research with the old and the new search and compare
search+fetch cost per research, cost per accepted value, and the number of paid calls on a repeat
run.

**Acceptance Scenarios**:

1. **Given** a search query run less than its cache lifetime ago, **When** the same query is needed
   again, **Then** the stored result is used and no paid search call is made.
2. **Given** a page fetched less than its cache lifetime ago, **When** it is needed again, **Then**
   the stored copy is used and no request is sent to the site.
3. **Given** the configured provider is unavailable or out of credit, **When** research runs,
   **Then** the configured fallback provider is used if one is set; otherwise the affected sections
   are marked "search unavailable" and the turn still completes.
4. **Given** a site is on the deny-list or its robots directives forbid the page, **When** a search
   result points to it, **Then** it is never fetched, and the skip is recorded.
5. **Given** a section is still below its minimum after the planned queries, **When** the depth and
   budget allow another round, **Then** the AI may propose at most a configured number of extra
   queries; code checks them against the deny-list and the budget before any is run.
6. **Given** the operator changes the provider in configuration, **When** the service restarts,
   **Then** research uses the new provider with no other change.

---

### User Story 3 - Honest answer when the request does not fit the budget or usage (Priority: P2)

A user gives a purchase budget, a monthly or yearly running-cost limit, or usage conditions (annual
mileage, mountains, towing, family size, city only). Before writing a report the hub checks these
against the data and says plainly when the request is impossible, possible only as a used car (with
an age range), or possible only with a different car class — or it asks one clarifying question when
the answer depends on something it does not know.

**Why this priority**: silently producing a report for an impossible request wastes the user's time
and money and breaks trust; it is the second most visible failure in live use.

**Independent Test**: golden dialogues with budget-infeasible, running-cost-infeasible and
usage-infeasible requests; each must produce an explicit feasibility verdict (or one clarifying
question) before any report.

**Acceptance Scenarios**:

1. **Given** "a new Land Cruiser for €25,000", **When** the official price from the manufacturer
   is far above the budget, **Then** the hub says a new one is not possible within the budget, shows
   the official price, and offers the options: used (with an estimated age range) or a different
   car, before any report.
2. **Given** a running-cost limit of €150 per month and 30,000 km per year, **When** the computed
   ownership cost of a car exceeds it, **Then** the hub says so with the computed figure and its
   assumptions and asks whether to continue or look at cheaper alternatives.
3. **Given** "a city car for regular mountain trips with four people and luggage", **When** the
   car's data shows the boot or power is clearly insufficient for the stated use, **Then** the hub
   names the mismatch with the numbers.
4. **Given** a budget is stated but it is unclear whether the user means new or used, **When** a new
   car would not fit but a used one might, **Then** the hub asks one clarifying question instead of
   assuming.
5. **Given** a feasibility verdict depends on data that is insufficient, **When** the check runs,
   **Then** the hub says the check could not be completed and why, rather than declaring the request
   feasible.

---

### User Story 4 - Delete old chats (Priority: P2)

A user opens the chat list and deletes chats they no longer need, one at a time or several at once,
after a confirmation. Everything that belongs only to those chats disappears; the shared knowledge
about cars (catalog, validated values and their sources) stays and keeps serving other chats.

**Why this priority**: the chat list grows with every test and becomes unusable; users also expect
to be able to remove their conversations.

**Independent Test**: create chats with research, delete them, and check that they are gone from the
list and from storage, that a reconnect to a deleted chat does not bring it back, and that cached car
data is still reused by a new chat without new searches.

**Acceptance Scenarios**:

1. **Given** a chat in the list, **When** the user deletes it and confirms, **Then** it disappears
   from the list and opening its address shows "this chat was deleted".
2. **Given** a chat whose turn is running or waiting for a confirmation, **When** the user deletes
   it, **Then** the running work is cancelled first and then the chat is deleted.
3. **Given** a deleted chat that had triggered research for a car, **When** a new chat asks about the
   same car, **Then** the validated data is reused and no new search is made within its freshness.
4. **Given** the user selects several chats, **When** they confirm deletion, **Then** all selected
   chats are deleted in one action.

---

### User Story 5 - One database for development and deployment (Priority: P3)

The operator runs the same database in development and in the deployed stack. Existing data from the
current development database (chats, cases, catalog, validated values, sources, usage) is moved into
it once, and cached search results and pages are kept only as long as their configured lifetimes.

**Why this priority**: two separate databases split the knowledge collected so far; the cache needs
retention so storage does not grow without limit.

**Independent Test**: migrate the current development data, compare record counts per kind before
and after, open an old chat and confirm the history and case are intact; run the retention job and
confirm only expired cache entries are removed.

**Acceptance Scenarios**:

1. **Given** the existing development data, **When** the one-time migration runs, **Then** the
   counts of chats, messages, cases, catalog variants, sources and validated values match exactly.
2. **Given** expired search results and pages, **When** retention runs, **Then** they are removed
   while sources referenced by validated values are kept.
3. **Given** the deployment script, **When** the operator deploys, **Then** the deployed service and
   local development use the same database setup and migrations.

### Edge Cases

- Favourite site changed its page layout: the site parser finds no table → the page falls back to
  general reading; a parser failure rate above a threshold is reported to the operator.
- A page lists several engines or generations in one table: only the column or row for the exact
  variant is used; if it cannot be isolated the values are rejected as ambiguous.
- Units and number formats differ by market (CV/PS/hp/kW, "1.480 kg", "6,1 s", mpg): normalised by
  the deterministic unit layer before validation.
- A PDF brochure or price list: read as a document; if it cannot be read the page is skipped with a
  reason.
- A site blocks the fetcher or rate-limits it: the page is skipped, the site's pacing is respected,
  other sources continue.
- Search results consist mostly of deny-listed classifieds: they are dropped before fetching; if
  nothing is left the section uses the next query.
- The search provider returns zero results for a site-restricted query: the next favourite or the
  open-web query is used.
- Old cars (over 25 years) or cars not sold in the user's market: fewer favourites apply; the early
  warning from 002 still shows; feasibility checks state what is unknown.
- Budget given in another currency or as a monthly instalment: the hub asks once how to interpret it
  rather than guessing.
- Deleting a chat while a different chat is researching the same car: the shared research for the
  car continues for the other chat.
- Migration finds records that violate current rules (e.g. duplicates): they are reported, not
  silently dropped.

## Requirements *(mandatory)*

### Functional Requirements

**Search (US2)**

- **FR-001**: The system MUST access web search only through one search interface with
  interchangeable providers; the provider and an optional fallback MUST be chosen in configuration
  without code changes. The default provider returns Google search results.
- **FR-002**: Search queries MUST be built by code from the case (exact variant, generation, years,
  market, language, research area) and query templates in configuration. Free browsing by an AI is
  not allowed.
- **FR-003**: For each research area the system MUST query the configured favourite sources for
  that area and the user's market/language first (site-restricted queries), and MUST use open-web
  queries for an area only when the favourites did not meet its minimum.
- **FR-004**: An extra round of AI-proposed queries MAY run only for areas still below their minimum,
  only when the research depth allows another round, limited to a configured number of queries per
  area; every proposed query MUST be checked by code (deny-list, budget, length) before it runs. The
  AI that proposes queries MUST NOT see page text.
- **FR-005**: Search results and fetched pages MUST be stored with their retrieval time and reused
  within a configured lifetime per kind (search results, pages by research area); reuse MUST NOT
  create a paid call.
- **FR-006**: Every paid search call MUST be recorded in the turn's usage with provider, kind, cost
  and research area, as in 002.

**Fetching and reading pages (US1, US2)**

- **FR-007**: The system MUST fetch pages itself, respecting robots directives, the deny-list,
  per-site rate limits, timeouts and size limits (constitution VIII). Deny-listed sites MUST never be
  searched for, fetched or read.
- **FR-008**: The system MUST extract the main readable content of HTML pages and PDF documents,
  dropping navigation, ads and boilerplate, before any AI reads it.
- **FR-009**: For favourite specification sites listed in configuration the system MUST read
  specification tables with deterministic site readers (no AI) and map them to canonical attributes
  and units. When a site reader fails, the page MUST fall back to general reading and the failure
  MUST be counted per site.
- **FR-010**: Values read by site readers MUST carry the same provenance (source, excerpt, retrieval
  time, source type) as values extracted by AI.

**Favourite sources (US1)**

- **FR-011**: Configuration MUST define favourite sources per research area (specifications,
  engineering, instrumented tests, official price, maintenance, reliability, reviews, used-car
  issues, manufacturer) and per market/language (at least ES, EN, DE), each with its source type and
  priority. The deny-list stays and always wins.
- **FR-012**: The source list shown to the user MUST indicate which sources were favourites and why
  a page was rejected when it was.

**Relevance and validation (US1)**

- **FR-013**: Before any value is extracted, each page MUST be checked for relevance to the exact
  requested variant: make, model, generation, production years, engine/trim, body and market where
  known. Pages about another generation, engine or body MUST be rejected with a stated reason; pages
  covering several variants MUST be used only for the parts that can be isolated.
- **FR-014**: Each extracted value MUST pass plausibility checks by attribute and vehicle class
  (configured ranges) and unit normalisation; implausible values MUST be rejected with a reason.
- **FR-015**: Value selection MUST keep the 002 conflict and confidence rules; values from a single
  low-authority source MUST NOT be shown as validated where the section minimum requires agreement.
- **FR-016**: The validator role MUST compare claims with the case (requested variant, market,
  condition, year, user's stated use) as well as with the page, and MUST be able to reject a claim
  that is true for the page but not for the user's car.
- **FR-017**: Research results per area MUST record: pages found, pages rejected by reason, values
  accepted, values rejected by reason, minimum met or not — available to the operator and in the
  evaluation reports.

**Feasibility of the user's constraints (US3)**

- **FR-018**: The case file MUST record the user's constraints when stated: purchase budget (with
  new/used intent and currency), running-cost limit (per month or year), annual mileage, and usage
  conditions (mountains, towing, passengers and luggage, city/highway mix, climate).
- **FR-019**: Before a report, the system MUST evaluate each stated constraint for each car with
  deterministic rules and produce a verdict per car: fits, does not fit, fits only as used (with an
  estimated age range), fits only with another class, or cannot be checked (with the missing data
  named).
- **FR-020**: When any car does not fit, fits only as used, or cannot be checked, the hub MUST state
  the verdict with the numbers and their sources or assumptions before (or instead of) the report,
  and offer the options; it MUST NOT silently produce a normal report.
- **FR-021**: When the verdict depends on an unknown that changes the answer (e.g. new or used,
  currency, financing), the hub MUST ask one clarifying question instead of assuming; questions
  follow the 002 limits (one round, at most three questions).
- **FR-022**: The used-car age range for a budget MUST be estimated in two steps: (1) a base estimate
  from the official new price and a configured depreciation curve by class and age, labelled
  "assumption" with its inputs shown; (2) refined by used-price ranges quoted in editorial sources
  (buying guides, reviews, reliability/used-car articles from favourite sources) for the exact
  generation, when found — each range shown with its source and date. Classifieds and listing
  portals MUST NOT be used (deny-list). When editorial ranges and the base estimate disagree, both are
  shown and the editorial range wins for the verdict. Used-price research is an extra research area
  that runs only when a budget check needs it and counts towards the turn budget.
- **FR-023**: Usage mismatches (e.g. boot volume vs. passengers and luggage, power-to-weight vs.
  mountains or towing, range vs. daily distance) MUST use configured thresholds and show the numbers
  compared.

**Storage (US5)**

- **FR-024**: Development and deployment MUST use the same database setup and the same schema
  migrations; the deployment script and the development start script MUST both use it.
- **FR-025**: A one-time migration MUST move all existing development data into it and report record
  counts per kind before and after; mismatches MUST fail the migration.
- **FR-026**: Retention MUST remove cached search results and pages after their lifetime, except
  pages that support validated values, and MUST run on a schedule or at start without manual steps.

**Chat deletion (US4)**

- **FR-027**: The user MUST be able to delete one or several chats from the chat list after a
  confirmation.
- **FR-028**: Deleting a chat MUST cancel its running or waiting turn first, then remove the chat,
  its messages, case file versions, turns, events, saved conversation state, and chat-scoped research
  tasks and usage records.
- **FR-029**: Deleting a chat MUST NOT remove the vehicle catalog, validated values, their sources
  and evidence, or research results shared with other chats.
- **FR-030**: A deleted chat MUST NOT come back on reconnect or reload; its address MUST show that it
  was deleted.

**Limits ask, never cancel (added 2026-11-02 from live use)**

- **FR-032**: When research approaches a per-turn limit (AI calls, cost or time), the system MUST pause
  and ask the user whether to continue or to answer with what was collected, showing what was spent
  and how many tasks are left. "Continue" grants one more allowance of each limit and resumes only the
  unfinished tasks; "answer" writes the report from the collected data with a small reserve kept for
  the answer. Research MUST NOT be cancelled silently by a limit; a hard safety timeout remains only
  for runaway turns.

**Measurement**

- **FR-031**: The evaluation harness MUST report, per research run and over a benchmark list of
  cars: share of research areas meeting their minimum, wrong-variant rejection count, search+fetch
  cost, cost per accepted value, paid calls avoided by the cache, and site-reader success rate per
  site.

### Key Entities

- **Search provider**: a configured source of web search results (name, kind, cost per call,
  fallback order).
- **Favourite source**: a site with its research areas, markets/languages, source type, priority,
  and whether a deterministic site reader exists for it.
- **Search result record**: a query, provider, market/language, results (address, title, snippet,
  rank), retrieval time, expiry.
- **Page record**: an address, fetch time, status, content type, main-content text, size, expiry,
  link to the site reader used (if any); referenced by evidence.
- **Relevance verdict**: page × requested variant → relevant / other variant (which) / ambiguous /
  not about a car, with reason.
- **Research area result**: per car × area × round: pages found, rejected by reason, values
  accepted/rejected by reason, minimum met.
- **User constraints**: purchase budget (amount, currency, new/used intent), running-cost limit,
  annual mileage, usage conditions; part of the case file.
- **Used-price range**: generation × age band → price range, with source (editorial article), date
  and market; or a base estimate from the official price and depreciation curve, labelled
  "assumption".
- **Feasibility verdict**: per car × constraint: fits / does not fit / used only (age range) /
  another class / cannot be checked, with the numbers, sources and assumptions used.
- **Chat deletion**: the act of removing a chat and everything scoped to it, recorded for audit
  (time, chat, record counts), without its content.

## Success Criteria *(mandatory)*

Baseline: measured on the 002 build with the current search, on the same benchmark list.

### Measurable Outcomes

- **SC-001**: On a benchmark list of at least 20 well-documented cars (built in the last 15 years,
  sold in Spain), at least 80% of research areas meet their minimum evidence after a Standard
  research (baseline: about 42% for instrumented tests, 43% for official price).
- **SC-002**: Search and page-retrieval cost of a new 2-car Standard research falls by at least 70%
  against the baseline on the same cars.
- **SC-003**: Cost per accepted value (search + retrieval + AI) falls by at least 50% against the
  baseline.
- **SC-004**: Zero values from a wrong generation, engine or body appear in reports on the benchmark,
  including at least 8 known generation traps; at least 95% of pages about a wrong variant in a
  labelled sample are rejected before extraction.
- **SC-005**: For favourite specification sites with a site reader, at least 90% of their pages are
  read without AI, and the values read match reference data within the attribute tolerance.
- **SC-006**: Repeating a research within the cache lifetime makes zero paid search calls and zero
  page requests to sites.
- **SC-007**: In golden dialogues with budget-, running-cost- and usage-infeasible requests, 100% end
  with an explicit feasibility verdict or one clarifying question before any report; none produces a
  silent normal report.
- **SC-007a**: For budget checks that return "fits only as used", 100% show an age range with either
  an editorial source or the labelled assumption and its inputs; zero values come from classifieds.
- **SC-008**: Deleting a chat removes 100% of its chat-scoped records, it never reappears after
  reload or reconnect, and a new chat about the same car reuses the cached car data with zero new
  searches.
- **SC-009**: After the one-time migration, record counts per kind match exactly and every migrated
  chat opens with its history and case intact.
- **SC-010**: A new 2-car Standard research still completes within 3 minutes for 90% of runs (002
  target kept).

## Assumptions

- The default search provider is a Google results provider (Serper); the provider interface also
  allows others (e.g. Parallel, Brave, the current provider) as alternatives or fallback. Exact
  prices are verified on the providers' official pages before use and kept in configuration.
- The initial favourite sources are drawn from the sites already typed in configuration (spec
  databases, instrumented-test magazines, manufacturer sites, reliability surveys) plus
  market-specific sites for ES/EN/DE; the operator can edit the list. Classifieds and secondary-market
  sites stay deny-listed.
- Deterministic site readers are built first for the three to five favourite specification sites
  that cover most cars; others use general reading.
- Default cache lifetimes follow the 002 freshness per area (e.g. price 30 days, specifications 365
  days); search results expire sooner than pages (default 7 days).
- Plausibility ranges by attribute and class are configuration and start conservative (reject only
  clearly impossible values).
- One user (single-tenant) as in 002; chat deletion is a hard delete after confirmation; no undo.
- The one database is PostgreSQL in Docker (constitution: single primary database); the embedded
  development database is retired after migration.
- The current model per role stays; model provider evaluation is the next feature. UI changes are
  limited to chat deletion and showing rejection reasons in the existing source list; the UI redesign
  is a later feature.
- Used-price ranges come only from editorial articles (FR-022), never from classifieds or listing
  portals; collecting secondary-market listing prices stays out of scope.
- Out of scope: secondary-market listing prices and classifieds, report export, multi-user accounts, external
  access for desktop AI clients, import of own documents.
