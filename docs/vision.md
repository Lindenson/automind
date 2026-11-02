# AutoMind: Agreed Product Vision (2026-11-01)

This document is the input for re-specifying feature 001 (`/speckit-specify`). It supersedes the
scope of the current `specs/001-car-battle-mvp/spec.md` where they differ. Governing rules are in
`.specify/memory/constitution.md` v1.1.0.

## 1. Concept

AutoMind is a **conversational automotive research system**. The user chats with a **hub
agent**, a knowledgeable car expert, who answers from validated cached knowledge or starts a
**research loop**. In that loop, LangGraph agents, internet search, and AutoMind's deterministic
MCP tools find, parse, validate, enrich, and store data. Results are shown as beautiful,
profile-specific reports and comparisons of **2–3 cars**.

## 2. User profiles

| Profile | Interest | Report focus |
|---|---|---|
| **Tech enthusiast** | How the car is engineered | Powertrain and engine architecture, transmission, chassis and suspension, design, platform, manufacturer history and market position |
| **Performance / race enthusiast** | How fast and how fun | Dynamics, power-to-weight, measured vs claimed performance, drag race simulations, driving-pleasure score |
| **Smart buyer** | A sound purchase | Reliability, maintenance schedule and costs, reviews (expert and owner), practicality (boot, seats, consumption and range), official price; practicality score |

Profile criteria and weights are configurable.

## 3. Research areas (MVP)

1. **Technical data**: Tier 1–3 specs (see spec 001 FR-010..FR-012), engineering details of
   units and design.
2. **Scheduled maintenance**: intervals (km and months), work items, costs of scheduled work when
   published (manufacturer or official dealer fixed-price menus). Otherwise a **deterministic
   estimate** (labour hours × configured rate + parts class), labeled "assumption".
3. **Reviews**: expert (publications) and owner; pros and cons; recurring vs isolated.
4. **Reliability**: known technical issues, ADAC/TÜV statistics, recurring owner complaints;
   rule-based score.
5. **Official price**: the manufacturer's recommended retail price in Spain (PVP), with date,
   trim, and whether taxes are included. No promotions. **No secondary-market data** (classifieds
   portals such as coches.net have no open API and forbid scraping).
6. **Manufacturer**: history, key models, current market position, with sources.

Running-cost inputs (fuel and electricity prices for ES, labour rate) are configuration values.

## 4. Quality: research-grade, not superficial

- Minimum evidence per section, for example: key specs = manufacturer + 1 independent source;
  maintenance = manufacturer schedule or 2 independent sources; reviews ≥ 5 from ≥ 2 sources.
- Bounded research loop until the minimum is met; otherwise the section is marked **"insufficient
  data"**.
- Validation before storing: excerpt-in-source check, variant match, conflict rules (authority
  order → majority), units, plus a validator role.
- **Depth levels**: Quick / Standard / Deep, which set the LLM-call budget and number of loops.
- Sources: search API plus direct page fetching (robots respected, rate limited, deny-list for
  sites forbidding automated access).

## 5. Architecture

```text
User ⇄ Frontend (React+TS) ⇄ WebSocket ⇄ API (FastAPI) ⇄ LangGraph
LangGraph:
  Hub agent (chat, intent, model identification and refinement, routing, final answer)
    ├─ cache check (deterministic, DB): fresh → answer directly
    ├─ Research subgraph: plan → search/fetch → extract (web readers, NO tools)
    │                     → validate → store (cache)
    ├─ Profile agents: Tech / Performance / Smart buyer   (analysts, scoped MCP tools)
    ├─ Comparison agent (2–3 cars, profile aspects)
    ├─ Race agent (simulation runs and explanation)
    └─ Report/conclusions agent → typed UI blocks (cards, tables, charts)
MCP server (deterministic, no LLM): catalog/cache DB, parsing and normalization, metrics,
  race physics v0.1, maintenance-cost estimate, reliability score, profile scores, chart
  data, report templates
Storage: PostgreSQL (domain + cache + LangGraph checkpoints), files for documents
Search: Tavily (default), Brave (alt), fixtures (tests and offline demo)
LLM: provider-independent gateway (Anthropic / OpenAI), model per role
```

- **Chat-first**: the hub is the main interaction. Some steps are deterministic (no LLM), some
  are LLM.
- **Cache**: freshness per category, configurable. Defaults: specs 365 d, reliability and reviews
  180 d, maintenance 365 d, manufacturer and market 30 d, official price 30 d.
- **Model input**: free text or a pasted URL (manufacturer or Wikipedia page). The hub proposes
  an exact variant, and the user corrects it on the next step if needed.
- **Chat language**: replies in the user's language (RU / EN / ES); site UI in English.
- **Chat history** is persisted and resumable.
- **General questions** ("how does a turbo work?") are answered with the label "general
  knowledge, no source". Car-specific numbers are given only with sources.

## 5a. Conversation intelligence: lessons from the concept demo (2026-11-01)

The demo proved the mechanics (search, validation, cache, deterministic calculations, MCP), but
the hub was "deaf" in real dialogues. Observed failures:

- A used, ~10-year-old Prado 150 was researched as a new Prado J250 twice.
- "I asked about the 150, not the 250" was not understood as a correction, although a Prado 150
  already existed in the catalog.
- The user's persona (a 20-year-old, a family buyer, an expert) was ignored, and so was "status"
  as a priority.
- No clarifying questions were asked; no ownership-cost report; the same report for everyone.

The MVP therefore MUST add the following.

**A. Case file (conversation memory).** A structured, persisted record per chat, updated every
turn:
- **who**: persona (expert / performance enthusiast / everyday or family buyer), experience, age
  if stated;
- **what**: new or used, model years or age, mileage, budget, usage (city / mountains / motorway
  / track / family);
- **priorities**, with weights: reliability, status, comfort, performance, ownership cost,
  practicality;
- **cars under discussion**, with exact generation and year;
- **decisions and results already shown**, so they are not repeated.

The user can see and edit the case file.

**B. Hub as a conversation lead.** Each turn the hub chooses one action: **ask** (1–3 clarifying
questions when key facts are missing), **answer from context** (no new research), **correct**
(replace or refine a car using the catalog first), **research gaps** (profile-driven), or
**report**. It never silently repeats a previous answer.

**C. User-derived criteria.** Wishes ("status", "mountains", "cheap to own") map to criteria from
a defined criteria dictionary. The proposed weights are shown and adjustable, and code computes
the scores. Criteria without data are reported as "insufficient data".

**D. Used-car scenario.** Age or year selects the generation. Research covers age- and
mileage-related known issues, big-ticket maintenance due at that age (timing belt, gearbox,
suspension, corrosion), and owner reviews of that generation. No secondary-market listings.

**E. Ownership cost (TCO) report.** Annual and 5-year figures: scheduled maintenance, energy,
tyres, road tax (IVTM) if found, big-ticket items by age, and a repair reserve for used cars.
Every figure is labelled sourced or assumption.

**F. Persona-specific reports.** Content, depth and language adapt to the persona: engineering
depth for experts, dynamics and race for enthusiasts, plain-language reliability, cost and
practicality for everyday buyers.

**G. Real research loop.** Gaps are determined from the case file's criteria; bounded multi-round
research; reviews and reliability research (ADAC/TÜV, owner forums).

**H. Dialogue regression tests.** Real demo conversations (Prado 150 correction, BMW 320d vs Golf
R-Line for a 20-year-old, "and if I prefer status?") become golden scenarios the hub must pass.

Also fix: catalog de-duplication (the same variant was stored twice); tool outputs must label
score parts vs raw metrics clearly.

## 6. Kept from the earlier spec (still valid)

Local vehicle catalog and reuse; conflict resolution by authority order, then majority of ≥2
independent same-rank sources; confidence HIGH/MEDIUM/LOW with defined rules; provenance labels
and deterministic assignment; excerpt validator; drag race v0.1 (ICE/BEV/hybrid, race settings,
prediction); bounded limits and cost tracking; restart recovery and cancellation; no report
export in MVP.

## 7. Delivery

- **Concept demo (mini-MVP)**: done 2026-11-01 (see `docs/concept-demo.md`); lessons in §5a.
- **Full MVP**: re-specify 001 from this document, then clarify → plan → tasks → analyze →
  implement. Accepted effort: about 140–180 h.
- **Later**: game-engine-style visuals, import of own PDFs, external MCP access for Claude
  Desktop, secondary-market prices.
