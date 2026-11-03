# Feature Specification: Electrified Cars and Chinese Brands — Correct Data, Honest Running Costs

**Feature Branch**: `006-electrified-cars`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "006 — Electrified cars (HEV, MHEV, PHEV, BEV) and Chinese brands: correct data, honest running costs, comparisons that make sense." (full text in the commit that created this file; summarised below)

## Background: what went wrong on 2026-11-03 (chat 5be54966)

The user compared a **BYD Seal U DM-i** (plug-in hybrid) with a **SEAT Ateca 1.5 TSI DSG** (petrol) for a family in the south of Spain, at 12,000–24,000 km a year. The identity was right after spec 005, but the report was unfair:

1. **No energy cost for the BYD.** The only consumption found for the BYD was the WLTP *weighted* figure, 0.9 l/100 km. It was rejected (as a unit error), and it is useless for costs anyway: it assumes daily charging and a short trip mix. So the BYD's ownership cost had **no energy line** (€688 a year, flagged as implausible), while the SEAT had €2,580 a year of petrol. The cheaper-looking car was simply missing its biggest cost.
2. **Electric data not modelled.** Battery size was found (18.3 kWh). Electric range, electric consumption (kWh/100 km), fuel consumption with an empty battery, charging power and time, and battery warranty are not modelled at all.
3. **One electricity price, wrong PHEV formula.** One electricity price serves every case. The plug-in "real-world" allowance multiplies the weighted figure (0.9 × 1.8 = 1.6 l/100 km), which is nonsense.
4. **Brand and climate ignored.** The dealer and service network of a new brand in Spain, its warranty, and its residual value were not researched. The hot climate of the south (air conditioning, battery heat) was ignored.

Electrified cars are now a large share of the Spanish market, and most Chinese brands sell only them. A report that cannot price their energy correctly misleads exactly the buyers who need it most.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Every car has an honest energy cost (Priority: P1)

Whatever the powertrain (petrol, diesel, mild hybrid, full hybrid, plug-in hybrid, electric), the ownership cost shows an energy line. Its inputs are visible: consumption with its source, price per litre or kWh, km per year and the share driven on electricity. A plug-in hybrid's cost comes from its electric consumption, its electric range, its fuel consumption with an empty battery, and how much of the user's driving can be electric. It never comes from the weighted WLTP figure.

**Why this priority**: without it every comparison with an electrified car is wrong, and the incident pair shows it.

**Independent Test**: for the incident pair (BYD Seal U DM-i vs SEAT Ateca 1.5 TSI DSG, 18,000 km a year), the report shows an energy line for both cars. The BYD line has electric kWh and petrol litres, each with its source and price.

**Acceptance Scenarios**:

1. **Given** a plug-in hybrid with sourced electric consumption, electric range and empty-battery fuel consumption, **When** the ownership cost is computed, **Then** it splits the yearly distance into electric and fuel km and prices each part. The split and its reasons (daily distance, home charging, range) are shown.
2. **Given** a plug-in hybrid where only the weighted WLTP figure is found, **When** the cost is computed, **Then** the weighted figure is not used. The empty-battery consumption is looked for again. If it is still missing, the energy line says "cannot be computed — missing: fuel consumption with an empty battery", and the verdict does not count running cost as a win for either car.
3. **Given** an electric car, **When** the cost is computed, **Then** it uses kWh/100 km (real-world where sourced, else WLTP with a documented allowance) plus charging losses, priced at the user's mix of home and public charging.
4. **Given** a petrol, diesel or full hybrid car, **When** the cost is computed, **Then** it is unchanged from today (WLTP plus the real-world allowance, or a sourced real-world figure).

---

### User Story 2 — The electric facts a buyer needs (Priority: P1)

For electric and plug-in cars the report shows:

- **Battery**: usable and gross capacity, and its chemistry where sourced (LFP, NMC…).
- **Range**: WLTP and real-world (summer, winter, motorway where sourced).
- **Consumption**: kWh/100 km.
- **Charging**: home (AC) charging power and full-charge time, fast (DC) peak power and 10–80 % time.
- **Battery warranty**: years, km and the minimum capacity guaranteed.
- **Equipment**: heat pump, vehicle-to-load and towing capacity.

Every value has a source. Values that contradict their meaning are rejected:

- kWh read as kW;
- gross capacity read as usable;
- a weighted figure read as a real consumption;
- a range above what the battery allows.

**Why this priority**: these facts decide whether an electrified car fits the user's life; today they are missing or unchecked.

**Independent Test**: research a Tesla Model 3, an MG4 and a BYD Seal U DM-i. Each report shows these attributes with sources. The sense-rule regression set (wrong units, gross vs usable, weighted WLTP, impossible ranges) is rejected.

**Acceptance Scenarios**:

1. **Given** a page that states "60 kWh" for charging power, **When** it is checked, **Then** it is rejected as a unit confusion (power is kW, energy is kWh).
2. **Given** a range larger than usable capacity ÷ a plausible minimum consumption, **When** it is checked, **Then** it is rejected as implausible.
3. **Given** only a gross battery capacity, **When** usable capacity is needed, **Then** the gross value is shown as gross. It is not used as usable without a documented allowance labelled "assumption".
4. **Given** a real-world range test (summer or winter), **When** it is found, **Then** it is stored as measured, with its conditions, separately from WLTP.

---

### User Story 3 — Spanish energy prices and the user's charging situation (Priority: P1)

The prices behind the energy costs are Spanish, visible, labelled as assumptions or sourced facts with their date, and changeable by the user:

- home electricity: regulated (PVPC) average, a typical fixed tariff, and a night-time price;
- public slow (AC) and fast (DC) charging price ranges of the main Spanish networks;
- petrol and diesel prices (by region when sourced).

Whether the user can charge at home changes the cost a lot. When it matters (an electric or plug-in car is compared and the answer would change the result), the hub asks once: "Can you charge at home or at work?" Otherwise it assumes and says so.

**Why this priority**: electricity at home and on a motorway fast charger can differ by four or more times; one price makes every EV comparison wrong.

**Independent Test**: the same BEV costs clearly more per 100 km with "no home charging" than with "home, night tariff". Both scenarios show their price inputs and dates.

**Acceptance Scenarios**:

1. **Given** an electric or plug-in car in the comparison and no answer about home charging, **When** the answer would change the cheaper car, **Then** one question is asked, and the cost waits for it or shows both scenarios.
2. **Given** the user says "no garage, only street parking", **When** costs are computed, **Then** public charging prices are used and the report says so.
3. **Given** a price older than its freshness period, **When** it is used, **Then** it is shown with its date and refreshed at the next research.
4. **Given** the user types their own price ("I pay 0.12 €/kWh at night"), **When** costs are computed, **Then** that price is used and marked as the user's.

---

### User Story 4 — Climate and the way the user drives (Priority: P2)

Range and consumption depend on the climate and on motorway driving. The case already knows the region's climate (spec 005) and the user's usage. Real range and consumption are adjusted by documented assumption factors per climate zone and motorway share. Examples:

- hot south: air conditioning load, battery temperature management;
- cold or mountain: winter losses, heating.

The report says which factors were applied.

**Why this priority**: it makes the numbers realistic for the user's place and use; it is an adjustment on top of US1–US3.

**Independent Test**: the same BEV in "Sevilla, mostly motorway" and "Asturias, city" shows different real ranges and costs, and the factors applied are listed.

**Acceptance Scenarios**:

1. **Given** a HOT region and mostly motorway use, **When** real range is estimated, **Then** the hot-climate and motorway factors are applied and named.
2. **Given** a sourced real-world range for similar conditions, **When** it exists, **Then** it is used instead of the factors.

---

### User Story 5 — A fair verdict and Spanish incentives (Priority: P2)

The verdict and the ownership cost compare like with like. If an energy line is missing for one car, running cost is not used to pick a winner, and the report says why. For an electrified car against a combustion car, the report shows the break-even: in how many years, at the user's km, the price difference is paid back by lower running costs.

Spanish incentives and advantages are shown as sourced facts with dates:

- the purchase subsidy programme;
- the income-tax deduction;
- the environmental label (ZERO or ECO) and what it allows: low-emission zones, parking;
- reduced road tax in the user's municipality where found.

They are never assumed, and an expired programme is shown as expired.

**Why this priority**: the incentives and the break-even are often what decides the purchase; they must be right or absent.

**Independent Test**: for BYD Seal U DM-i vs SEAT Ateca at 18,000 km a year, the report shows:

- the break-even in years, with its inputs;
- the labels (ZERO vs C);
- the current subsidy status with its source and date.

**Acceptance Scenarios**:

1. **Given** a purchase price difference and yearly running costs for both cars, **When** the break-even is computed, **Then** it is shown in years, rounded, with the inputs. "Never" is shown when the electrified car is not cheaper to run.
2. **Given** a subsidy programme found with an end date in the past, **When** it is shown, **Then** it is labelled expired and not subtracted from the price.
3. **Given** no sourced information about the municipal road-tax reduction, **When** the report is written, **Then** it says "not found" instead of a figure.

---

### User Story 6 — New brands: warranty, network, reputation, resale (Priority: P2)

For brands new in Spain (BYD, MG, Omoda, Jaecoo, Leapmotor, Xpeng, Zeekr…), and for every make, the report shows:

- the warranty terms (car and battery);
- the size of the dealer and service network in Spain, and the nearest points to the user's region where sourced;
- parts availability and recalls from reviews;
- residual value where data exists.

When residual value data is scarce, the report says so.

**Why this priority**: a cheap car with no workshop within 100 km or with unknown resale is a risk the buyer must see.

**Independent Test**: for BYD in "south of Spain" the report states the warranty terms and the dealer count in Spain with sources and dates. Residual value is either sourced or marked "insufficient data for this brand".

**Acceptance Scenarios**:

1. **Given** a sourced dealer count, **When** shown, **Then** it carries its source and date. No count is ever estimated.
2. **Given** a battery warranty "8 years or 160,000 km, 70 %", **When** read, **Then** years, km and the guaranteed capacity are stored as separate checked values.

---

### User Story 7 — The electric section in the report (Priority: P3)

The report gets a compact "electric" section, in the user's language (ru/es/en):

- real and WLTP range;
- charging times for the user's case (overnight at home, a 10–80 % stop on a trip);
- the cost per 100 km at home and in public;
- for plug-in hybrids, the share of electric driving.

The ownership cost shows its energy split (electricity vs fuel). Short explainers cover the terms: weighted WLTP, empty-battery consumption, usable capacity, DC peak vs average.

**Why this priority**: presentation of the facts from US1–US6; valuable but only after the numbers are right.

**Independent Test**: for an MG4 vs VW ID.3 report, the section exists, both cars have the same rows, gaps are marked, and the texts are in the chat language.

**Acceptance Scenarios**:

1. **Given** two electric cars, **When** the report is shown, **Then** the electric section lists the same attributes for both, with "not found" marks where missing.
2. **Given** one electric and one combustion car, **When** the report is shown, **Then** the electric section covers the electric car, and the cost section compares both on cost per 100 km.

### Edge Cases

- **Two figures named "consumption" for a plug-in hybrid** (weighted 0.9 l/100 km and real 5.6 l/100 km): the meaning is decided from the words around each value (weighted, combined, charge-sustaining, empty battery), never from the size of the number alone.
- **Mild hybrids sold as "hybrid"**: they never get electric driving shares.
- **Range-extender cars** (an engine that only charges the battery): treated like plug-ins for energy, with their own label.
- **Electric consumption with or without charging losses**: the basis is recorded. Losses are added only once.
- **The user charges at work for free**: a price of zero is accepted when the user says so, and it is marked as the user's.
- **Daily distance unknown**: the electric share comes from km per year with a documented assumption, and the report says so.
- **A brand with no Spanish network data**: "not found", and a suggestion to check before buying.
- **A used electric car** (battery health): shown only if sourced. Full used-car mode is spec 007.
- **Prices in another currency or country** (UK range tests, US prices): range tests are allowed with their conditions; prices are never taken from another market.

## Requirements *(mandatory)*

### Functional Requirements

**Energy model**

- **FR-001**: Every car in an ownership cost MUST have an energy line, or an explicit "cannot be computed" with the missing inputs named.
- **FR-002**: For plug-in hybrids the energy cost MUST be computed from:
  - electric consumption (kWh/100 km);
  - electric range;
  - fuel consumption with an empty battery;
  - the share of electric driving.
  The weighted WLTP figure MUST NOT be used as a fuel consumption.
- **FR-003**: The electric share MUST be derived from the daily distance (or km per year), the electric range (real-world when available), the ability to charge at home or at work, and a documented assumption for charging habits. It MUST be shown with its inputs.
- **FR-004**: For electric cars the energy cost MUST use kWh/100 km (real-world if sourced, else WLTP plus a documented allowance) and charging losses added once, priced by the user's home/public mix.
- **FR-005**: Combustion and non-plug-in hybrids keep today's model (sourced real-world figure, else WLTP or NEDC with a documented allowance).

**Electric attributes and their checks**

- **FR-006**: The catalog MUST hold, with sources:
  - usable and gross battery capacity;
  - battery chemistry;
  - electric range (WLTP; real-world with conditions);
  - electric consumption;
  - charge-sustaining fuel consumption;
  - AC onboard charger power;
  - DC peak power;
  - DC 10–80 % time;
  - battery warranty (years, km, guaranteed capacity);
  - heat pump, vehicle-to-load and towing capacity.
- **FR-007**: Meaning rules MUST reject:
  - energy and power units confused;
  - gross capacity presented as usable;
  - a weighted WLTP figure filed as a consumption;
  - ranges above what the usable capacity allows;
  - DC times or powers outside plausible bounds;
  - charging power above the battery's plausible maximum C-rate.
- **FR-008**: The meaning of a consumption value MUST be decided from the words around it (weighted / combined / charge-sustaining / electric). An unclear value MUST NOT be used.
- **FR-009**: The research for an electric or plug-in car MUST look for these attributes specifically. A missing attribute that the energy model needs MUST be researched again (deeper) before the cost is marked "cannot be computed".

**Energy prices and charging situation**

- **FR-010**: Spanish energy prices MUST be configured as visible assumptions or sourced facts with dates:
  - home electricity: regulated average, typical fixed, night;
  - public AC and DC charging ranges;
  - petrol and diesel.
  They MUST be overridable by the user in the chat.
- **FR-011**: The ability to charge at home or at work MUST be part of the profile. It MUST be asked at most once, only when an electric or plug-in car is compared and the answer can change the result. Otherwise it MUST be assumed and labelled.
- **FR-012**: The home/public charging mix MUST be derived from the profile and shown.

**Climate and use**

- **FR-013**: Real-world range and consumption MUST be adjusted by documented assumption factors for the region's climate zone and the motorway share of usage, unless a sourced real-world value for similar conditions exists. The factors applied MUST be listed.

**Fair verdict and incentives**

- **FR-014**: When one car lacks an energy line, running cost MUST NOT decide the verdict, and the report MUST say why.
- **FR-015**: The break-even of an electrified car against a combustion car MUST be computed by code in years at the user's km, with inputs. "Never" is shown when it does not pay back.
- **FR-016**: Spanish incentives and advantages MUST be shown only as sourced facts with dates and status (active or expired):
  - the purchase subsidy;
  - the income-tax deduction;
  - the environmental label and its benefits;
  - municipal road-tax reductions.
  An expired or unsourced incentive MUST NOT change the price.

**Brands**

- **FR-017**: For every make, the warranty terms (car and battery) and the size of the Spanish dealer and service network MUST be researched and shown with sources and dates. Counts MUST NOT be estimated.
- **FR-018**: Residual value for electrified cars and new brands MUST be shown when sourced. When data is scarce it MUST be marked "insufficient data", never filled from other brands.

**Report**

- **FR-019**: The report MUST include an electric section when an electric or plug-in car is compared. It lists the same rows for each car, marks gaps, and is in the chat language.
- **FR-020**: The ownership cost MUST show the energy split (electricity / fuel) and the price inputs.
- **FR-021**: Explainers MUST exist for: weighted WLTP, charge-sustaining consumption, usable vs gross capacity, DC peak vs average power, charging losses.

**Measurement**

- **FR-022**: The system MUST record, per report:
  - cars without an energy line;
  - rejected EV values by rule;
  - the number of times a weighted figure was offered as a consumption and blocked.

### Key Entities

- **Electric attributes of a version**: battery usable and gross capacity, chemistry, ranges (WLTP; real-world with conditions), electric consumption, charge-sustaining consumption, charging powers and times, battery warranty, heat pump, vehicle-to-load, towing. Each value has a source and provenance (manufacturer claim, measured, sourced fact, derived, assumption).
- **Energy price**: kind (home regulated, home fixed, home night, public AC, public DC, petrol, diesel), value with unit, market, date, source or "assumption", and an optional user override.
- **Charging situation**: home or work charging available (yes / no / unknown), the evidence words, and the derived home/public mix.
- **Energy estimate**: per car, the km split by energy, the consumption used per part with its basis, the prices, the factors applied (climate, motorway, losses), and the yearly cost; or "cannot be computed" with the missing inputs.
- **Incentive**: programme or advantage, scope (national, regional, municipal), amount or effect, valid-from and valid-to, status, source.
- **Brand presence**: make, market, dealer count, service-point count, warranty terms, date, source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the incident pair (BYD Seal U DM-i vs SEAT Ateca 1.5 TSI DSG, 18,000 km a year), 100 % of reports show an energy line for both cars with visible inputs.
- **SC-002**: Zero reports use a weighted WLTP plug-in figure as a fuel consumption, in the regression set and in live chats.
- **SC-003**: The sense-rule regression set for electric values passes 100 %:
  - unit confusions;
  - gross vs usable;
  - weighted vs charge-sustaining;
  - impossible ranges;
  - implausible charging figures.
- **SC-004**: The golden dialogues pass:
  - BYD Seal U DM-i vs SEAT Ateca;
  - Tesla Model 3 vs BMW 320d;
  - MG4 vs VW ID.3;
  - Toyota RAV4 hybrid vs Kia Sportage plug-in;
  - a used Nissan Leaf with battery health.
- **SC-005**: For electric and plug-in cars, at least 80 % of researched versions have electric range, electric consumption and DC charging figures with sources.
- **SC-006**: The home-charging question is asked in at most 1 message per chat, and only in chats with an electric or plug-in car where it changes the result.
- **SC-007**: Every incentive shown has a source and a date; zero expired incentives are subtracted from a price.

## Assumptions

- Spain is the market for prices, incentives and networks, as in specs 002–005. Range tests from other countries are allowed with their conditions.
- Energy prices are configured defaults with dates. They are shown as assumptions until a sourced update exists, and users can override them.
- Climate and motorway factors are documented assumptions until sourced real-world data for similar conditions is found.
- The habit assumptions behind the electric share (how often a plug-in is charged) are documented, visible and overridable.
- Used-car specifics (battery health over time, used prices) are spec 007. Only sourced battery-health facts are shown here.
- No new paid data providers. Search and configured sources only (constitution X).
- The identity work of spec 005 (engine, open-world brands, intake card) is in place.
