# Research: Research Quality and Search v2

**Feature**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Date**: 2026-11-02

Baseline facts (dev DB, 2026-11-02): Tavily search 77 calls / 154 credits ≈ €1.14, Tavily extract 26
calls / 52 credits ≈ €0.39; all LLM calls ≈ €0.55 (interpreter 45%, reporter 22%, extractor 20%).
Research jobs: measured empty 7/12, price empty 4/7; reliability claims accepted 33 / rejected 39.
Current pipeline (`application/research.py`): code-built queries (`config/queries.yaml`) → Tavily
search (advanced, 4 results/query) → Tavily extract for snippet-only docs → LLM extractor per page →
programmatic checks → validator for uncertain pages → selection.

## R1. Search provider: Serper as default, behind a provider port

- **Decision**: New port `SearchProvider` (`search(query, *, gl, hl, num) -> list[SearchHit]`)
  with adapters `serper` (default), `tavily` (kept as fallback; no extract), and later `parallel` /
  `brave`. Provider and fallback order in `config/search.yaml`; key per provider from env
  (`SERPER_API_KEY`, `TAVILY_API_KEY`, …). Results are hits (url, title, snippet, rank) only — page
  text always comes from our own fetcher (R4). Serper call: `POST https://google.serper.dev/search`
  with `q`, `gl` (country), `hl` (language), `num` (10). Cost per call in `config/prices.yaml`
  (`search.serper.per_query`), verified on serper.dev before release (vendor pages list ≈ $1 per
  1,000 queries on the smallest pack; deeper `num` may cost more credits — measured, not assumed).
- **Rationale**: we need precise Google results for site-restricted queries (`site:`), which is
  exactly what a SERP API returns; extraction and validation are ours. Serper is ≈ 10–15× cheaper per
  query than Tavily advanced search and has no per-page extraction fee.
- **Alternatives**: Parallel (LLM-ready excerpts, own index, $1–5 per 1,000; we would pay for
  excerpts we re-read anyway — kept as a possible adapter); Brave (independent index, weaker for
  `site:` coverage of niche ES/DE sites); Google Custom Search JSON API (closed to new customers,
  shut down 2027-01-01); keep Tavily (measured as poor value).

## R2. Query strategy: favourites first, open web second, AI follow-up last

- **Decision**: per job (car × area × round):
  1. **Favourite round**: one query per favourite *group* for the area and the user's market —
     `{make} {model} {generation} {variant} site:a.com OR site:b.com OR site:c.com` (≤ 4 sites per
     query, ordered by priority), with `gl/hl` of the market (ES: `es/es`, EN: `gb/en` or `us/en`,
     DE: `de/de`). Templates and site groups come from `config/sources.yaml` (R5).
  2. **Open-web round** (only if the area minimum is not met): the existing area templates from
     `config/queries.yaml`, deny-listed domains excluded with `-site:` for the three biggest
     classifieds and filtered again in code.
  3. **AI follow-up round** (only DEEP depth, or STANDARD with budget left, area still below
     minimum): role `query_planner` (cheap model, structured output, no tools, **no page text**)
     receives the variant identity, the area, missing attributes and the queries already tried; it
     returns ≤ 3 queries. Code rejects queries that mention deny-listed domains, exceed 200 chars, or
     repeat earlier ones, and checks the budget before running them.
- **Rationale**: specialised sites hold the numbers; the open web is a fallback, not the default.
  Grouping sites with `OR` keeps calls low (one call covers several favourites).
- **Alternatives**: one query per favourite site (more precise, 3–4× more calls — used only when a
  grouped query returns nothing); free AI browsing (forbidden by FR-002 and constitution VIII).

## R3. Caching search results and pages in Postgres

- **Decision**:
  - `search_cache`: key = sha256(provider | normalised query | gl | hl | num); stores hits JSON,
    `fetched_at`, `expires_at` (default 7 days; configurable per area).
  - `documents` is extended into a page store: `url_hash` (unique), `final_url`, `status`,
    `content_type`, `fetched_at`, `expires_at` (from the area's freshness, R8 of 002: price 30 d,
    specs 365 d, reviews/reliability 180 d), `reader` (site reader id or `main_content`),
    `fail_reason`. Reuse by URL inside its lifetime makes no network request.
  - Lookups happen in the provider wrapper and the fetcher, so callers cannot bypass the cache.
  - Cache hits are recorded in usage as `cached: true` with cost 0 (FR-005, FR-006, SC-006).
- **Rationale**: identical queries recur across chats and turns; the 002 code paid every time.
- **Alternatives**: HTTP-level cache (no control over expiry per area, no audit); Redis (second
  store, constitution: one primary database).

## R4. Own fetching and main-content extraction

- **Decision**: reuse `infrastructure/fetch.py` (deny-list → robots → per-host rate → timeout →
  type/size limit) and extend it:
  - honour `Crawl-delay` from robots.txt (e.g. ultimatespecs = 30 s) on top of the configured
    minimum interval; a robots.txt fetch that returns 401/403 means "disallow all" (whatcar.com
    returned 403 on robots.txt on 2026-11-02);
  - follow redirects (≤ 5) and re-check deny-list and robots for the final URL;
  - concurrency ≤ 2 per host, ≤ 8 global;
  - HTML main content with **trafilatura 2.3** (Apache-2.0) — `extract(..., include_tables=True,
    output_format="markdown")` so tables survive as text for the extractor; fall back to the current
    `html_to_text` if trafilatura returns nothing;
  - PDF with **pypdf 6** (BSD-3) text extraction, first 30 pages;
  - pages whose main content is shorter than 400 characters are marked `fail_reason="no content"`
    (typical for JavaScript-only pages) — no headless browser in this feature.
- **Rationale**: we already own the policy-compliant fetcher; Tavily extract cost 52 credits for
  26 pages and returned unstructured text without tables.
- **Alternatives**: headless browser (heavy, slow, not needed for the favourite sites — they render
  server-side); the provider's scrape endpoints (cost per page and robots responsibility moves to a
  third party; rejected under constitution VIII).

## R5. Favourite sources in configuration

- **Decision**: `config/sources.yaml` gains `favourites:` — a list of sites with `domain`,
  `source_type` (the existing 002 types: MANUFACTURER, INSTRUMENTED_TEST, SPEC_DATABASE,
  PUBLICATION, ENCYCLOPEDIA — reviews, reliability surveys and buying guides are PUBLICATION), `areas`, `markets` (ES/EN/DE/ANY), `priority` (1–3), `reader` (site reader id or
  null), `tos_checked` (date the operator reviewed the site's terms; readers run only when set).
  Initial list (robots checked for our user agent on 2026-11-02 — all allow the sample car pages):

  | Area | ES | EN | DE |
  |---|---|---|---|
  | specs / engineering | km77.com, motor.es, fichasmotor.com | ultimatespecs.com, auto-data.net, cars-data.com, parkers.co.uk | adac.de (Autokatalog), auto-data.net |
  | measured | km77.com (pruebas), autopista.es | caranddriver.com, evo.co.uk, autoexpress.co.uk | auto-motor-und-sport.de, autobild.de |
  | price | manufacturer `.es` sites, km77.com (precios) | — | — |
  | maintenance | manufacturer sites, km77.com | honestjohn.co.uk, parkers.co.uk | adac.de |
  | reliability / used_issues | km77.com, autopista.es | honestjohn.co.uk, whatcar (search only) | adac.de (Pannenstatistik), autobild.de (TÜV) |
  | reviews | km77.com, autopista.es, motor.es | evo.co.uk, autoexpress.co.uk, carwow.co.uk | auto-motor-und-sport.de, autobild.de |
  | used_price (R11) | km77.com, autopista.es | honestjohn.co.uk, parkers.co.uk (valuations articles) | adac.de, autobild.de |

  Wikipedia stays an `ENCYCLOPEDIA` source for generation years and codes. The deny-list is checked
  first and always wins.
- **Rationale**: the operator controls quality by editing data, not code (constitution X).
- **Alternatives**: hard-coded site lists (not editable); learning favourites from acceptance rates
  automatically (later — the per-site metrics of FR-017 make it possible).

## R6. Deterministic site readers

- **Decision**: `infrastructure/site_readers/` with one module per site, each a pure function
  `read(html, url) -> SiteReading | None` returning rows `(attribute, raw_value, raw_unit, excerpt)`
  where `excerpt` is the table row text (so 002 excerpt validation still applies). Mapping of site
  labels → canonical attributes lives in `config/site_readers.yaml` (e.g. km77 "Potencia máxima" →
  `max_power`). First readers: **km77.com** (ES "datos" tables), **ultimatespecs.com**,
  **auto-data.net**; a fourth (**adac.de** Autokatalog) if time allows. Parsing with selectolax
  (MIT) CSS selectors. A reader returns `None` when the layout is not recognised → the page goes to
  the LLM extractor (FR-009); failures are counted per site (`site_reader_stats`). Tests use saved,
  trimmed HTML fixtures (only the table fragments).
- **Multi-variant pages**: a reader returns rows only for the column/section whose heading matches
  the variant (engine code, power, years); if none matches uniquely it returns
  `ambiguous=True` and nothing is accepted from that page.
- **Rationale**: table pages are where LLM extraction wastes most tokens and makes unit mistakes;
  readers are exact and free.
- **Alternatives**: LLM-only extraction (current; costly and noisier); generic table heuristics
  (labels differ per site and language — mapping per site is simpler and testable).

## R7. Relevance gate before extraction

- **Decision**: new pure module `domain/relevance.py`:
  `judge(page: PageFacts, target: VariantIdentity, siblings: list[GenerationInfo]) -> Relevance`.
  Deterministic signals: generation codes of the target and of sibling generations in title/URL/
  first 2,000 chars (existing `_mentions`, `_sibling_code`), production years mentioned vs. the
  generation's years, engine signature (displacement, power in kW/PS/CV/hp within ±5%, fuel), body
  words, make/model presence. Verdicts: `RELEVANT`, `OTHER_VARIANT(which)`, `MULTI_VARIANT`,
  `NOT_ABOUT_CAR`, `UNCERTAIN`. Only `UNCERTAIN` pages go to a cheap LLM relevance check (role
  `relevance`, web reader, no tools, structured output, sees ≤ 3,000 chars + the case identity).
  `OTHER_VARIANT` / `NOT_ABOUT_CAR` pages are rejected with the reason stored on the page record and
  shown in the source list (FR-012, FR-013).
- **Rationale**: 002 decided relevance inside the extractor after paying for extraction; rejecting
  early saves tokens and stops wrong-generation values at the door (SC-004).
- **Alternatives**: LLM relevance for every page (cost); keep relevance inside extraction (status
  quo, measured as leaky).

## R8. Plausibility rules

- **Decision**: `config/plausibility.yaml` — ranges per canonical attribute, optionally per
  powertrain and class (e.g. `measured_0_100: ICE {min: 2.3, max: 25}`, `curb_mass {min: 600,
  max: 3800}`, `max_power_kw {min: 30, max: 1200}`, `boot_l {min: 50, max: 2500}`, `price_eur {min:
  5000, max: 600000}`), plus cross-attribute checks (power-to-weight ≤ 1 kW/kg for road cars; claimed
  0–100 vs power-to-weight band). Pure `domain/plausibility.py`; implausible → claim status
  `REJECTED_IMPLAUSIBLE` with the rule id. Ranges start conservative (reject only the impossible).
- **Rationale**: FR-014; cheap, deterministic, testable.
- **Alternatives**: LLM plausibility (non-deterministic; constitution III).

## R9. Case-aware validator

- **Decision**: the validator prompt receives, besides the page excerpt and claims, the **case
  identity** (make, model, generation, years, engine/trim, body, market, condition, year of the
  user's car) and may answer `SAME_VARIANT`, `OTHER_VARIANT`, `OTHER_MARKET`, `OTHER_YEAR`,
  `UNSUPPORTED`. The validator runs (a) for pages with `MULTI_VARIANT`/`UNCERTAIN` relevance, and
  (b) for claims that disagree with an already selected value beyond tolerance. It stays a web reader
  without tools (constitution VIII).
- **Rationale**: FR-016 — a value can be true for the page and wrong for the user's car (another
  market's power rating, a facelift year).
- **Alternatives**: validating every claim with the LLM (cost); no case context (status quo).

## R10. User constraints in the case file

- **Decision**: `CaseFile.constraints`: `budget {amount, currency, intent: NEW|USED|ANY|UNKNOWN,
  kind: TOTAL|MONTHLY}`, `running_cost_limit {amount, period: MONTH|YEAR}`, `annual_km` (exists),
  `usage {mountains, towing_kg, passengers, luggage: LOW|MEDIUM|HIGH, city_share, daily_km,
  climate}`. The interpreter fills them through `CaseDelta.set_constraints` with
  `constraints_evidence` (verbatim words from the current message); code drops numbers that do not
  appear in the evidence (same rule as `persona_evidence` in 002). The case panel shows them and lets
  the user edit them (PATCH case).
- **Rationale**: FR-018; numbers must not be invented (constitution I).

## R11. Feasibility engine and used-price estimate

- **Decision**: pure `domain/feasibility.py`:
  - inputs: constraints, per-car facts (official price, TCO per year from `tco.py`, boot, seats,
    power-to-weight, range, condition, age), used-price ranges, rules from `config/feasibility.yaml`;
  - checks: `budget` (new price vs budget; if over → used age range), `running_cost` (TCO/period vs
    limit), `usage` (passengers+luggage vs boot/seats; mountains/towing vs kW/t and towing capacity;
    daily km vs BEV range);
  - verdict per car × check: `FITS`, `DOES_NOT_FIT`, `USED_ONLY(age_from, age_to)`,
    `OTHER_CLASS`, `UNKNOWN(missing)`; each with the numbers compared and their provenance.
  - **Used-price estimate (clarification Q1 = C)**: base = official new price × depreciation curve
    by class and age from `config/feasibility.yaml` (e.g. compact: 1 y 0.78, 3 y 0.60, 5 y 0.47, 8 y
    0.33, 12 y 0.20), labelled ASSUMPTION; refined by **editorial** used-price ranges (new research
    area `used_price`: buying guides, used reviews, valuation articles from favourites; claims
    `used_price_min/max_eur` with model years and market). When both exist and disagree, both are
    shown and the editorial range decides the verdict. Classifieds are never used (deny-list).
  - The `used_price` area is planned only when a budget is stated and the new price does not fit or
    the car is used.
- **Rationale**: FR-019–FR-023; deterministic verdicts with numbers (constitution III).
- **Alternatives**: LLM judgement of feasibility (non-deterministic, unverifiable).

## R12. Policy: verdict before report

- **Decision**: extend `domain/policy.decide`:
  - before research: if a budget is stated with `intent=UNKNOWN` and the answer would differ for new
    vs used → `ASK` with new question kind `BUDGET_INTENT` (and `BUDGET_CURRENCY` / `BUDGET_KIND`
    only when ambiguous), inside the 002 limits (one round, ≤ 3 questions);
  - after research, before `REPORT`: compute feasibility; if any car has a verdict other than
    `FITS` and the user has not acknowledged this verdict set (`case.feasibility_ack` = fingerprint
    of constraints + verdicts) → new action `FEASIBILITY` (reply = verdict block + options: "show the
    report anyway", "look at used", "suggest alternatives"). Acknowledging (button or text) stores
    the fingerprint, then `REPORT` follows in the same or the next turn.
  - `UNKNOWN` verdicts caused by insufficient data are shown as "could not be checked" (FR-020 #5).
- **Rationale**: no silent report for an impossible request (SC-007), without blocking the user.
- **Alternatives**: verdict only inside the report (users miss it — the 002 failure).

## R13. Research area results and metrics

- **Decision**: `research_jobs` gains counters by reason (`pages_found`, `pages_cached`,
  `pages_rejected` JSON {reason: n}, `values_rejected` JSON {reason: n}, `reader_used` n,
  `queries` JSON); `site_reader_stats` (domain, day, ok, failed); usage rows for searches carry
  `provider`, `cached`. The eval harness `tests/eval/test_research_quality.py` (live) runs a
  benchmark list `backend/eval/research_benchmark.yaml` (≥ 20 cars incl. ≥ 8 generation traps) and
  writes a report with SC-001..SC-006 metrics; it can be run with `SEARCH_PROVIDER=tavily` for the
  baseline and with the default for the new build.
- **Rationale**: FR-017, FR-031; the success criteria need a before/after on the same cars.

## R14. One Postgres for development and deployment

- **Decision**: Docker Compose Postgres 16 for both. `docker-compose.yml` keeps the deploy stack;
  a `docker-compose.dev.yml` override publishes Postgres on `127.0.0.1:5433` (5432 may be taken).
  `scripts/dev.sh` starts `postgres` via compose, runs migrations, starts the API on the host.
  `scripts/db.sh` (embedded pgserver) is retired after the migration. One-time
  `scripts/migrate-embedded.sh`: start embedded server → `pg_dump --format=custom` (pgserver ships
  pg_dump 16) → `pg_restore` into the compose database → compare `count(*)` of every table (domain
  + checkpoint tables) → fail on mismatch → print a summary. Retention: an asyncio task in the API
  lifespan runs at start and every 24 h: delete expired `search_cache` rows; delete expired
  `documents` with no evidence pointing to them.
- **Rationale**: constitution (Docker Compose for local development, one primary database); FR-024
  –FR-026.
- **Alternatives**: keep embedded for dev (two setups drift); logical copy via SQLAlchemy (slower,
  error-prone; pg_dump is exact).

## R15. Chat deletion

- **Decision**: REST `DELETE /api/v1/chats/{chat_id}` and `POST /api/v1/chats/delete` (`{ids}`),
  idempotent. Steps per chat: `runner.cancel(chat_id)` and wait ≤ 5 s → one DB transaction deleting
  `chat_messages`, `case_files`, `turn_events`, `turns`, `research_jobs` (chat-scoped), `llm_calls`
  and `search_calls` with that `chat_id`, `chats` row → `AsyncPostgresSaver.adelete_thread(chat_id)`
  → insert tombstone `deleted_chats(chat_id, deleted_at, counts)` (no content). Shared data
  (`vehicle_variants`, `documents`, `evidence`, `claims`, `spec_values`, `research_runs`, area
  tables) is untouched. WebSocket `hello` for a tombstoned chat → `error{code:"chat_deleted"}` and
  close; REST reads → 410 Gone. Frontend: delete button per chat, multi-select, confirm dialog;
  `sessionStorage` seq for that chat is cleared.
- **Rationale**: FR-027–FR-030; shared research stays reusable (SC-008).
- **Alternatives**: soft delete (data stays; the user asked to remove); deleting usage history
  (kept only as chat-scoped rows per FR-028; aggregate cost per day can be kept later if needed).

## R16. Usage accounting and limits for the new calls

- **Decision**: Serper calls go through the existing `TurnBudget.before_search/after_search` with
  the provider's price; cache hits cost 0; fetches are free but limited by `max_pages_per_job`
  (default 8) and `max_fetch_bytes_per_turn`. New roles `query_planner` and `relevance` in
  `config/models.yaml` (cheap model) and in the cost estimator's per-area averages.
- **Rationale**: constitution VI (bounded, cost-visible); FR-006.
