# Feature Specification: Verified Source Registry and Data Found Where It Exists

**Feature Branch**: `009-source-registry`

**Created**: 2026-11-05

**Status**: Draft

**Input**: User description: "009 — Verified source registry: research finds data where it exists, learns which sources deliver, and records every lesson as a source update; plus the fixes shown by chat 20b5b7f9." (full text in the conversation of 2026-11-05; the incidents are summarised below)

## Context

The user judges the product by the quality of the data in its reports. Two live chats showed thin data and wrong numbers for some of the most common cars in the world.

**Chat 20b5b7f9 (2026-11-05).** Kia Sorento 2024 1.6 T-GDI PHEV 288 CV (new) against a Toyota Land Cruiser Prado J150 2010 3.0 D-4D 173 CV (used).
- **Kia fuel cost.** The Kia had no fuel-with-empty-battery consumption, so its ownership cost had no fuel at all. The report still compared ownership costs.
- **Prado price.** The Prado's used price (€18,400) came from a junk page: US-dollar "market entry floor" figures converted to euros. The user puts the real Spanish price at about €30,000.
- **Pages wrongly rejected.** Most rejected pages were rejected by our own "is this page about this car" check, not missing from search:
  - "manuales" was read as "manual gearbox";
  - a generation stored as the year "2024" rejected facelift pages of the same generation;
  - brand-wide service pages were rejected as "not about this car".
- **Searches without the year.** Searches for the 15-year-old car carried no year, so results were flooded by the new generation.

**Chat 8c6a2a58 (2026-11-04).**
- **A4 used price.** The only used price found for an Audi A4 2023 was a UK whole-generation range.
- **Warranty.** The brand's warranty pages are closed to robots, so the report said "no data".

**The user's direction:**
- "no data" is not acceptable when the data exists somewhere;
- search where the data is, on any market, not only on Spanish sites;
- keep a separately maintained list of verified sources per kind of data, and record every lesson as an update of that list;
- classifieds stay forbidden.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ownership costs are complete or not compared (Priority: P1)

A buyer compares a plug-in hybrid with a diesel. The report gives both cars a fuel cost. When the fuel-with-empty-battery figure is not published anywhere we can read, it is estimated from the official figures and labelled as an estimate. The report never compares ownership costs when one car lacks a main cost item; it says which item is missing.

**Why this priority**: The chat showed an ownership-cost comparison without the main cost of one car. That is a wrong conclusion presented as a fact, the worst failure for this product.

**Independent Test**: Replay chat 20b5b7f9 with stored data. The Sorento shows a fuel cost marked "estimate". With the estimate removed, no ownership-cost comparison appears, and the report names the missing item.

**Acceptance Scenarios**:

1. **Given** a PHEV with a known official weighted consumption, electric consumption and electric range but no sourced fuel-with-empty-battery figure, **When** the ownership cost is computed, **Then** the fuel-with-empty-battery consumption is estimated and the cost item says "estimate" with its inputs.
2. **Given** the user states their own consumption figure, **When** the cost is computed, **Then** the user's figure is used and labelled as theirs.
3. **Given** one car lacks energy, maintenance or depreciation, **When** the report is built, **Then** neither the verdict nor the text compares ownership cost, and the missing item is named for that car.

---

### User Story 2 - Used prices from where they exist, labelled, never junk (Priority: P1)

A buyer compares a used car. The used price comes from a trusted valuer or an editorial used-car guide. If no Spanish source gives it, it comes from another market, with the market, the currency and the conversion shown. A page that is not a price for that model year, such as a market floor, a whole-generation range or another currency without a basis, is never used.

**Why this priority**: The used price drives the verdict for a used car. A junk price (€18,400 against a real €30,000) misleads the user directly.

**Independent Test**: Replay chats 20b5b7f9 and 8c6a2a58.
- The Prado and A4 prices either come from labelled valuer or guide sources, or are shown as unavailable with the list of sources tried.
- The junk page is never used.

**Acceptance Scenarios**:

1. **Given** a used car with a year, **When** the used price is researched, **Then** the verified used-price sources for that kind of data are queried first on every market they cover, with the car's model year in the query.
2. **Given** a price found only on another market, **When** it is accepted, **Then** the report shows it as "price on market X, converted to €" with the source and date.
3. **Given** a page whose figures are a market floor, a range for the whole generation, or a currency or market with no conversion basis, **When** it is extracted, **Then** its figures are rejected and the reason is recorded against that source.
4. **Given** no verified source and no bounded open search gives a price, **When** the report is built, **Then** the report says which sources were tried, and a "find a source" gap is recorded.

---

### User Story 3 - A maintained list of verified sources per kind of data (Priority: P1)

The operator (and the assistant working on the code) keeps one reviewable list. For each kind of data, it says which sources deliver it, on which markets, with what status, and which lessons were learned. The kinds of data are used price, new price, specifications, plug-in and electric consumption, maintenance, warranty, residual value, reliability, measured performance and used-car issues.

Research reads this list. Every lesson from a live chat is written into it in the same change as the code fix.

**Why this priority**: Without a memory of what works, research starts from zero in every chat and keeps hitting Spanish sites that block us or hide data.

**Independent Test**: Open the registry. Every lesson from chats 8c6a2a58 and 20b5b7f9 is present with date, chat and outcome. A research run for a used price queries the verified used-price sources first.

**Acceptance Scenarios**:

1. **Given** the registry, **When** an operator reads it, **Then** each source shows the kinds of data it gives, its markets, its status (verified, candidate, blocked, junk, hides data), the date it was checked and its lessons.
2. **Given** a source marked junk or blocked for a kind of data, **When** research plans that kind of data, **Then** that source is not queried or read for it.
3. **Given** a fix for a live-chat flaw, **When** it is merged, **Then** the registry change that records the lesson is part of the same change.

---

### User Story 4 - The registry learns from every research run (Priority: P2)

After every research run, results are counted per source and kind of data:
- pages read and values accepted;
- robots refusals;
- pages rejected as "not about this car";
- values rejected.

Sources that keep failing are demoted, and candidates that keep delivering are proposed for promotion. The proposed changes are listed for review, and nothing is promoted to verified silently.

**Why this priority**: Manual curation alone goes stale. The numbers show where to look, and the review keeps the list trustworthy.

**Independent Test**: Run research against fixture searches where one source is always blocked and another always delivers. The statistics show both. The blocked source is demoted for that kind of data, and the delivering one appears in the proposed changes.

**Acceptance Scenarios**:

1. **Given** a source refused by robots in N consecutive runs for a kind of data, **When** the next run plans that kind of data, **Then** the source is skipped and the proposal lists it as blocked.
2. **Given** a non-registered source that delivered accepted values in M runs, **When** the operator asks for proposals, **Then** it is listed as a candidate with its counts.

---

### User Story 5 - Fewer good pages rejected by our own checks (Priority: P2)

Pages about the right car are kept:
- facelift pages of the same generation;
- the brand's service and warranty pages for maintenance and warranty data;
- pages whose words merely contain "manual".

Searches for a used car carry its year or generation and the model's name on that market (in Spain, "Land Cruiser" rather than "Prado").

**Why this priority**: In the chat, half the rejected pages were good pages thrown away by our own checks.

**Independent Test**: Re-judge the stored pages of chat 20b5b7f9. The pages listed in the diagnosis are kept, and pages of other generations are still rejected.

**Acceptance Scenarios**:

1. **Given** a page whose title or address contains "manuales" or "manuals", **When** the gearbox check runs, **Then** it does not count as "manual gearbox".
2. **Given** a car whose generation is recorded as a bare year, **When** pages are judged, **Then** the generation is mapped to its code and years, and pages of the same generation (including its facelift) are relevant.
3. **Given** the maintenance or warranty kind of data, **When** a brand-wide service, maintenance or warranty page names the make, **Then** it is relevant.
4. **Given** a used car from 2010, **When** its queries are built, **Then** they contain its year or generation, and the model name used on the market searched.

---

### User Story 6 - The dialogue flaws of chat 20b5b7f9 (Priority: P3)

- The first message is understood, never answered with "could not map".
- "Find me a Kia to replace my Prado" proposes Kia models that fit, instead of asking which model.
- The first identification of a 15-year-old car never picks an engine that did not exist in its year.
- The same car shows the same seat count and boot volume in every report of a chat.

**Why this priority**: These hurt trust, but the data issues above matter more.

**Independent Test**: Replay the chat's messages against fixtures and check each point.

**Acceptance Scenarios**:

1. **Given** the message "найди мне подходящую kia для замены моего ленд круер прадо 150 возрастом 15 лет", **When** it is the first message, **Then** the reply proposes 2–3 Kia candidates and recognises the Prado as the car to replace.
2. **Given** the Prado aged 15 years, **When** its engine is identified, **Then** only engines sold in that year are offered or chosen.
3. **Given** two reports in one chat, **When** they show the same car, **Then** its seats and boot volume are the same, unless the car's identity changed.

### Edge Cases

- **Currency without a basis.** A source on another market quotes a price in a currency with no dated exchange rate available: the value is not used, and the reason is recorded.
- **Registry conflicts with the deny-list.** A classifieds site or another deny-listed site appears in the registry: the deny-list wins, and the registry entry is rejected at load.
- **Status differs by kind of data.** A source verified for one kind of data is junk for another (a tyre dealer gives tyre prices, not car prices): the status is per kind of data.
- **Too little to estimate.** A PHEV estimate cannot be made because the official weighted figure or the electric range is missing: the energy cost is missing, and no ownership-cost comparison is shown.
- **Blocked only for some pages.** A source blocked by robots for some pages but not others: the status records the blocked path, not the whole site.
- **Unreviewed proposals.** Proposed registry changes that were never reviewed never change what research trusts.

## Requirements *(mandatory)*

### Functional Requirements

**Registry**

- **FR-001**: The system MUST keep a source registry. It is organised by kind of data: used price, new price, specifications, plug-in and electric consumption (including fuel with an empty battery), maintenance intervals and costs, warranty, residual value, reliability, measured performance and used-car issues. Each entry records:
  - the source (site or site section) and the markets it covers;
  - what it gives;
  - a status: verified, candidate, blocked, junk or hides data;
  - the date it was checked;
  - its lessons (date, chat or run, what happened).
- **FR-002**: The registry MUST be reviewable and versioned with the code.
- **FR-003**: The registry MUST be seeded from the current favourite sources, from the stored research history, and from the lessons of chats 8c6a2a58 and 20b5b7f9.
- **FR-004**: Deny-listed sites (classifieds and sites whose terms forbid access) MUST NOT be entered in the registry. Such an entry is rejected when the registry is loaded.
- **FR-005**: Statuses MUST be per kind of data. A path that robots refuse MUST be recorded as blocked for that path only.

**Statistics and proposals**

- **FR-006**: After every research run the system MUST count, per source and kind of data:
  - pages read;
  - values accepted;
  - robots refusals;
  - pages rejected as another car or not about the car;
  - values rejected with their reasons.
- **FR-007**: The system MUST skip a source for a kind of data after it has been refused by robots or judged junk in a configurable number of consecutive runs. The skip MUST be shown in the proposals.
- **FR-008**: The system MUST produce proposed registry changes for review: demotions, and new candidates with their counts. Proposals MUST NOT change which sources are verified until a reviewer accepts them.

**Research uses the registry**

- **FR-009**: For each kind of data, research MUST query the verified sources for that kind of data first, on every market they cover. Bounded open search follows. The Spanish market is preferred only when it has a verified source for that kind of data.
- **FR-010**: Values from another market MUST be accepted with the market labelled. Prices MUST be converted to euros with a dated rate and labelled as that market's price.
- **FR-011**: "No data" MUST be shown only after every verified source and a bounded open search have failed. The report MUST name the sources tried, and the system MUST record a "find a source" gap for that kind of data.
- **FR-012**: Classifieds MUST NOT be searched, read or used for any kind of data.

**Lessons as registry updates**

- **FR-013**: Every fix of a flaw found in a live chat MUST include the registry change that records its lesson. A check MUST list the lessons whose chat has no registry entry.

**Ownership cost (chat 20b5b7f9)**

- **FR-014**: For a plug-in hybrid without a sourced fuel-with-empty-battery consumption, the system MUST estimate it from the official weighted consumption and the official electric range. It uses the EU utility factor and the real-use allowance, and labels the result as an estimate with its inputs. A figure stated by the user wins.
- **FR-015**: The system MUST NOT compare ownership costs, in the verdict, the reasons, the text or the trade-off, when one car lacks energy, maintenance or depreciation. It MUST name the missing item for that car.

**Used price quality**

- **FR-016**: A used-price value MUST be rejected when any of these holds:
  - it is not for the car's model year;
  - it is a market floor or entry-level aggregate;
  - its currency has no dated conversion basis;
  - its source is junk for used prices.
- **FR-017**: Used-price searches MUST carry the car's model year and the model's market name.

**Relevance checks**

- **FR-018**: The gearbox and drive checks MUST match whole words only.
- **FR-019**: A generation recorded as a bare year MUST be mapped to the generation code and years that contain that year. Pages of the same generation, including its facelift, MUST be judged relevant.
- **FR-020**: For maintenance and warranty, a brand-wide service, maintenance or warranty page that names the make MUST be judged relevant.
- **FR-021**: Queries for a used car MUST carry its year or generation and the model name used on the market searched (for example "Land Cruiser" in Spain for the Prado J150).

**Dialogue (chat 20b5b7f9)**

- **FR-022**: A first message naming a make to choose from and a car to replace MUST lead to candidate proposals for that make, never to "could not map" or "which model?".
- **FR-023**: The first identification of a used car with a known age MUST offer or choose only engines sold in that year.
- **FR-024**: The seat count and boot volume of a car MUST be the same in every report of a chat, unless the car's identity changed. When two sources differ, the same rule picks the value every time.

### Key Entities

- **Kind of data**: what a source gives, such as used price, maintenance or PHEV consumption. It maps onto the existing research areas.
- **Registry entry**: a source × kind of data, with its markets, what it gives, status, date checked, path limits and lessons.
- **Lesson**: date, chat or run, what happened and the change made (for example "dealerportal.grouptyre.co.uk: US-dollar floor prices read as a used price; junk for used price; chat 20b5b7f9").
- **Run statistics**: per source × kind of data × run: pages read, values accepted, robots refusals, relevance rejections, value rejections.
- **Proposal**: a suggested registry change (demote, block, promote a candidate) with its evidence counts; it applies only after review.
- **Source gap**: a kind of data × car for which every verified source and the open search failed; it is input for finding new sources.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the replay of chat 20b5b7f9:
  - the Sorento has a fuel cost labelled as an estimate;
  - an ownership-cost comparison appears only when both cars have energy, maintenance and depreciation.
- **SC-002**: In the replays of chats 20b5b7f9 and 8c6a2a58, no used price comes from a junk or floor page. Each used price is from a labelled valuer or guide source, or shown as unavailable with the sources tried.
- **SC-003**: The share of fetched pages rejected by our relevance checks in the replay of chat 20b5b7f9 falls by at least half against the live run.
- **SC-004**: Every lesson of chats 8c6a2a58 and 20b5b7f9 is in the registry, and the lesson check reports none missing.
- **SC-005**: After the registry is in use, the share of research areas ending below their evidence minimum, for the cars of the last five live chats replayed, falls by at least a third.
- **SC-006**: No classifieds page is fetched in any test or live run.

## Assumptions

- **Reuse.** The kinds of data map onto the existing research areas (used_price, price, specs, maintenance, manufacturer for warranty, depreciation, reliability, measured, used_issues). Plug-in consumption is a part of specs with its own entries.
- **Who reviews.** The operator is the reviewer. Proposals are shown in a report or listing, not in the chat UI.
- **Exchange rates.** Dated exchange rates already exist for price conversion. GBP and USD are added where missing, with their date and source.
- **Thresholds.** The defaults for demotion and promotion (N, M) are configurable, starting at 3 runs.
- **Reuse of the existing pieces.** The favourites list and the learned sources counter are reused: the registry replaces the favourites list as the curated source, and learned sources feed the proposals.
- **Out of scope.** Classifieds, paid data providers and live dealer stock.
