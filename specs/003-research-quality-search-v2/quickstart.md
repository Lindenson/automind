# Quickstart: validating Research Quality and Search v2

Run guide for proving the feature end to end. Contracts: [contracts/](./contracts/); data:
[data-model.md](./data-model.md).

## Prerequisites

- Docker with Compose v2; the user can reach the Docker daemon (`docker info`).
- `.env` with `OPENAI_API_KEY`, `SERPER_API_KEY`, and `TAVILY_API_KEY` (fallback and baseline only).
- `uv` and Node 22 in `~/.local/bin`.

## 0. Baseline (before switching the provider)

```bash
cd backend
SEARCH_PROVIDER=tavily uv run pytest tests/eval/test_research_quality.py -m live -s   # writes eval/out/baseline-*.json
```

Expected: a report with per-area minimum-met share, search+fetch cost, cost per accepted value,
wrong-variant rejections — the numbers SC-001..SC-006 are compared against. Cost: several euros for
20 cars; run once.

## 1. One database (US5)

```bash
scripts/migrate-embedded.sh        # once: embedded .pgdata → Docker Postgres; prints counts per table
scripts/dev.sh                     # Postgres via compose (127.0.0.1:5433), migrations, API on :8000
```

Expected: the migration prints equal before/after counts for every table and exits 0; old chats
open with history and case (SC-009). `scripts/deploy.sh` uses the same compose Postgres service.

## 2. Gates

```bash
scripts/check.sh                   # ruff, mypy (domain), import-linter, pytest, frontend
```

New unit tests: relevance rules (generation traps), plausibility, feasibility (budget/new/used,
running cost, usage), search plan (favourite groups, market locale), site readers on saved fixture
fragments, cache keying, chat deletion scopes.

## 3. Search, cache, readers (US1, US2) — live

1. New chat: "BMW 520d G30 or Mercedes E 220 d W213, family buyer" → confirm variants and cost.
   - Status shows `searching` (favourites first) → `reading` → `relevance` → `validating`.
   - Sources block: favourite sources marked; rejected pages listed with reasons (e.g. "other
     generation: G60").
   - Specs section meets its minimum for both cars; values from km77/ultimatespecs/auto-data marked
     as read without AI.
2. Ask the same in a **new chat** → research is reused; usage shows 0 paid searches and 0 page
   fetches for areas within freshness (SC-006).
3. `GET /api/v1/research/metrics?days=1` → per-area minimum-met share, rejection reasons, reader
   success per site, search cost and cache hits.

## 4. Feasibility (US3) — golden dialogues

```bash
cd backend && uv run pytest tests/golden -k "feasib" -s           # replay (free)
uv run pytest tests/golden -m live -k "feasib" -s                 # live
```

Dialogues:
- G8 "a new Toyota Land Cruiser for €25,000" → `FEASIBILITY` with the official price, "new: does
  not fit", used age range (editorial range if found, otherwise labelled assumption) and three
  options; no report before the choice.
- G9 "up to €150 a month to run, 30,000 km a year, Golf GTI vs i30 N" → running-cost verdict with
  the TCO figure and its assumptions.
- G10 "a Fiat 500 for mountain trips with four people and luggage" → usage mismatch with boot litres
  and kW/t compared.
- G11 "I have €20,000, Golf or Leon?" (new/used unclear) → one `BUDGET_INTENT` question before
  research.

Expected: 100% end with a verdict or one clarifying question before any report (SC-007, SC-007a).

## 5. Chat deletion (US4)

1. UI: Chats → select two chats → Delete → confirm. They disappear from the list.
2. Reload a deleted chat's URL → "This chat was deleted" (WS `error.code = chat_deleted`, REST 410).
3. Delete a chat while its research runs → the turn is cancelled, then the chat is deleted.
4. New chat about a car researched in a deleted chat → no new searches within freshness (SC-008).
5. DB check: no rows with the deleted `chat_id` in chat-scoped tables; catalog/evidence counts
   unchanged.

## 6. Success criteria run

```bash
cd backend && uv run pytest tests/eval/test_research_quality.py -m live -s   # new build vs baseline
```

Expected: SC-001 ≥ 80% areas meet minimum; SC-002 search+fetch cost −70%; SC-003 cost per accepted
value −50%; SC-004 zero wrong-variant values, ≥ 95% wrong-variant pages rejected; SC-005 ≥ 90% of
favourite spec pages read without AI; SC-010 2-car research ≤ 3 min p90.
