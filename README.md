# AutoMind

AutoMind is a conversational car expert. You describe what you want in your own words (Russian,
Spanish or English); the hub keeps a **case file** about you and the cars, asks only what changes the
answer, confirms the exact variants, researches what is missing with validated sources, and answers
for *you*: a family buyer, a performance enthusiast or an engineer. Numbers come only from code; the
AI explains them.

- Vision: [docs/vision.md](docs/vision.md) · Rules: [.specify/memory/constitution.md](.specify/memory/constitution.md)
- Current feature: [specs/002-conversational-mvp](specs/002-conversational-mvp/) (spec, plan, tasks, contracts)
- Architecture decisions: [docs/adr](docs/adr/README.md)

## How a turn works

```text
user message
  → load case file → interpret (LLM → typed CaseDelta) → apply delta (code) → assess (catalog, research plan, cost)
  → policy (code) ──┬─ ANSWER_GENERAL        general knowledge, labelled "no sources"
                    ├─ ASK                   ≤3 template questions, one round
                    ├─ CONFIRM_VARIANTS      interrupt: "Prado J150 (2009–2023)?"   ─┐
                    ├─ CONFIRM_COST          interrupt: "about €0.42 — run it?"      ─┴→ resume → assess
                    ├─ RESEARCH              jobs per car × area (Send) → gap rounds ≤ depth → assess
                    ├─ ANSWER_FROM_CONTEXT   recompute from cache, no research ("nothing new" if unchanged)
                    └─ REPORT                compute (criteria, TCO, race, blocks in persona order)
                                             → persona reporter (scoped MCP tools) → number guard
```

One persistent LangGraph thread per chat (Postgres checkpointer); every event is stored with a
sequence number and replayed after a reconnect; usage (AI calls, tokens, searches, €) is counted per
turn for every role.

## Reading the code

Start with the pure rules, then go outwards (`backend/src/automind`):

| Layer | What to read first |
|---|---|
| `domain/` (pure, tested first) | `casefile.py` (memory), `policy.py` (what to do), `identity.py` (no 150/250 mix-ups), `research_plan.py`, `criteria.py`, `tco.py`, `reliability.py`, `reviews.py`, `evidence.py`, `dragrace.py` |
| `application/` | `interpret.py`, `resolve.py`, `research.py` (area workers), `extraction.py` (schemas, validator role), `compose.py` (blocks), `usage.py` |
| `orchestration/` | `graph.py`, `nodes/`, `runner.py` (turn lifecycle, cancel, resume), `prompts/*.md`, `agents.py` (tool scopes) |
| `infrastructure/` | `llm_gateway.py`, `usage_callback.py`, `search_tavily.py`, `fetch.py` (robots, deny-list), `db/`, `checkpoint.py`, `events.py` |
| `api/` | `ws.py` (protocol v2), `rest.py` (`/api/v1`), `app.py` (composition) |

Configuration is data, not code: `backend/config/*.yaml` (models per role, prices, sources and
deny-list, favourite sites, search provider, site readers, plausibility and feasibility rules, aliases,
generations, criteria, TCO rates, severity rules, search queries, questions).

## Research and search (spec 003)

- **Search**: `config/search.yaml` picks the provider (`serper` default; `serpapi`, `tavily` as alternatives or
  fallback; env `SEARCH_PROVIDER` overrides). Results and pages are cached in Postgres; a repeat search is free.
- **Favourite sites** per research area and market: `config/sources.yaml` → `favourites`. Table readers for
  km77, ultimatespecs and auto-data run only for sites whose terms the operator reviewed (`tos_checked`).
- **Relevance gate**: pages about another generation, engine or body are rejected before extraction; the
  sources block lists rejected pages with the reason.
- **Your case**: budget (new / used / either), running-cost limit, people, luggage, towing. The hub says when a
  request does not fit — before the report — and offers: report anyway, look at used ones, or alternatives.
- **Limits**: when research nears the per-turn limit of AI calls, cost or time, the hub asks whether to continue.
- **Operator metrics**: `GET /api/v1/research/metrics?days=7`. Old chats: delete them from the chat list.

## Reports (spec 004)

- **Verdict first**: a card with the pick or a tie, the reasons in numbers, the main trade-off (e.g. "pays back
  in 30 years"), a confidence with its reason and what would change it. Built by code
  (`domain/insights.py`, `domain/verdict.py`, thresholds in `config/insights.yaml`); the AI only explains, and
  `report_check` removes text that contradicts the blocks.
- **Trustworthy values** (`domain/sense.py`, `config/sense.yaml`): consumption per test cycle (WLTP, older NEDC,
  real-world), gear counts, service intervals, the market of prices and schedules, the gearbox and drive of the
  variant. After a rule change: `scripts/repair-data.sh` (back up first).
- **Exact cars**: unclear answers are asked again, unknown models are never invented, and every car is compared
  at the same equipment level (base by default; a named version sets the level).
- **Rich content**: value after 3 and 5 years, manufacturer situation, technology explainers
  (`config/tech_explainers.yaml`), model-year changes.
- **Dialogue**: one "what we know" panel with *Find it*, next-step suggestions, critique leads to research or
  a reworked report, *wrong?* on any value re-checks it, a 1–5 rating under each report.
- **Layout** per profile (`config/report_layouts.yaml`), research progress grid, interface in ru / es / en.

## Intake and identification (spec 005)

- **Every reply moves the identification forward.** Each car is identified again from its current facts in the same turn (`application/identify.py`). Questions come from localized templates (`config/questions.yaml` v2) with concrete options and are never sent twice. After 2 attempts the hub proposes a car itself.
- **Open-world brands.** Makes sold in Spain are in `config/makes.yaml`, with aliases and Cyrillic spellings. Their Spanish line-ups are looked up with sources (`application/lineup.py`, cached 30 days). "Find the matching model" proposes 1–3 models that fit the person, each with a reason. Links from classifieds sites are never read.
- **Corrections.** The engine is part of the identity ("1.5, not 1.0" works). A correction drops the old version and is shown as "before → after".
- **The person.** Region and climate (`config/regions.yaml`), km a year as a range, and new or used, asked once for all cars.
- **One confirmation card** before research: cars, profile and cost. Each item is marked stated, inferred, found or assumed and can be edited with chips. One "yes" starts the research.
- **Metrics.** `GET /api/v1/metrics` → `intake`: replies until the cars are confirmed, repeated questions, corrections, research on unconfirmed cars.
- **Engine back-fill** for stored variants: `scripts/repair-data.sh --engine` (back up first).

## Run locally (development)

```bash
# 1. Keys in .env (see .env.example): OPENAI_API_KEY, SERPER_API_KEY (TAVILY_API_KEY optional fallback)
# 2. Build the frontend once (Node 22 is in ~/.local/bin)
cd frontend && PATH=$HOME/.local/bin:$PATH npm install && npm run build && cd ..
# 3. Postgres 16 in Docker (127.0.0.1:5433), migrations, API on the host (also serves the frontend)
scripts/dev.sh
# 4. Open http://127.0.0.1:8000 (API_HOST=0.0.0.0 in .env makes it reachable from the local network —
#    there is no login yet, so anyone on the network can use it and spend the API budget)
```

`AUTOMIND_EMBEDDED_DB=1 scripts/dev.sh` uses the old embedded database in `./.pgdata` (no Docker).
The one-time copy of that database into Docker: `scripts/migrate-embedded.sh` (`--check` only compares counts).

For UI work: `cd frontend && npm run dev` (http://127.0.0.1:5173, proxied to the API); `?mock=1`
shows the UI with recorded data and no backend.

## Run with Docker (deployment)

```bash
scripts/deploy.sh              # build, start app + Postgres 16, migrate, wait until healthy → http://127.0.0.1:8080
scripts/deploy.sh status       # containers + health
scripts/deploy.sh logs         # follow app logs
scripts/deploy.sh backup       # pg_dump → backups/automind-<time>.sql.gz   (restore: scripts/deploy.sh restore <file>)
scripts/deploy.sh down         # stop (data kept);  destroy = stop and delete the database volume
```

- Keys come from `.env` (`OPENAI_API_KEY`, a search key such as `SERPER_API_KEY`); they are passed at run time,
  never baked into the image.
- On first run the script creates `.env.docker` (git-ignored) with a generated Postgres password. Port and bind
  address: `AUTOMIND_PORT` (default 8080, so it does not clash with `scripts/dev.sh` on 8000) and `AUTOMIND_BIND`
  (default 127.0.0.1; put a reverse proxy with TLS in front before exposing it).
- The container runs the Alembic migrations before uvicorn, runs as a non-root user and has a health check
  (`/api/v1/health`). Postgres is published on 127.0.0.1 only (port `AUTOMIND_DB_PORT`, default 5433) and
  is the same database `scripts/dev.sh` and the tests use.

## Tests and quality gates

```bash
scripts/check.sh                                  # ruff, format, mypy (domain), import-linter, pytest, frontend
cd backend
uv run pytest tests/unit                          # pure rules
uv run pytest tests/graph                         # graph mechanics: fake LLM + fixture search + real Postgres
uv run pytest tests/golden                        # golden dialogues G1–G7, replay (free)
GOLDEN_VERBOSE=1 uv run pytest -s tests/golden    # per-turn action, case, variants, duration
uv run pytest tests/golden -m live                # golden dialogues against real models (≈ €0.45)
uv run pytest tests/eval -m live -s               # used-car generation resolution, 22 cases (≈ €0.35)
uv run python eval/run_research_eval.py --label v2 --cars 1   # research quality on the benchmark (own DB)
```

Golden dialogues and their last live results: [backend/tests/golden/README.md](backend/tests/golden/README.md).

## Try this in the chat

1. "I don't want to spend too much, but I don't want rubbish either. A brand-new Dacia Bigster or a used Land Cruiser Prado?"
2. "about 10 years old, the 150" → confirm the J150 → report for a buyer with ownership cost
3. "if I prefer status, who wins?" (recomputed from cache, no new research)
4. "the same, but I'm a car engineer" (the report is reordered for an expert)
5. "Мне 20, могу купить б/у BMW 320d M Sport или Golf R-Line 4Motion — сравни на драг-рейсинг, город и горы"
