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
deny-list, aliases, generations, criteria, TCO rates, severity rules, search queries, questions).

## Run locally (no Docker)

```bash
# 1. Keys: put OPENAI_API_KEY and TAVILY_API_KEY in .env (see .env.example)
# 2. Build the frontend once (Node 22 is in ~/.local/bin)
cd frontend && PATH=$HOME/.local/bin:$PATH npm install && npm run build && cd ..
# 3. Start embedded Postgres, apply migrations and start the API (also serves the frontend)
scripts/dev.sh
# 4. Open http://127.0.0.1:8000
```

For UI work: `cd frontend && npm run dev` (http://127.0.0.1:5173, proxied to the API); `?mock=1`
shows the UI with recorded data and no backend.

## Run with Docker (deployment)

```bash
docker compose up --build      # http://127.0.0.1:8000
```

The image runs the Alembic migrations before starting uvicorn. Not yet verified on this machine
(Docker is not installed here).

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
```

Golden dialogues and their last live results: [backend/tests/golden/README.md](backend/tests/golden/README.md).

## Try this in the chat

1. "I don't want to spend too much, but I don't want rubbish either. A brand-new Dacia Bigster or a used Land Cruiser Prado?"
2. "about 10 years old, the 150" → confirm the J150 → report for a buyer with ownership cost
3. "if I prefer status, who wins?" (recomputed from cache, no new research)
4. "the same, but I'm a car engineer" (the report is reordered for an expert)
5. "Мне 20, могу купить б/у BMW 320d M Sport или Golf R-Line 4Motion — сравни на драг-рейсинг, город и горы"
