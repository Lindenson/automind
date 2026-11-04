# Quickstart: validating spec 008

## Prerequisites

- Docker Postgres is up (`automind-postgres-1`, port 5433).
- `.env` has the model keys. `.env.docker` gives `TEST_DATABASE_URL`.
- `cd backend && uv run alembic upgrade head` creates `model_versions` (0013).

## Automated

```bash
scripts/check.sh   # ruff, mypy, import-linter, unit, integration, graph, golden, frontend
cd backend && uv run pytest tests/unit/test_version_ladder.py tests/unit/test_ladder_property.py \
  tests/unit/test_used_costs.py tests/unit/test_incident_9b5c0b0c.py -q
```

Expected results:
- **Ladder unit tests:**
  - Octavia 2.0 diesel → POWER question 116/150;
  - A4 2023 2.5 → missing "2.5" + only the 2023 engines;
  - one engine with FWD/AWD → DRIVE only.
- **Property test:** ≥ 1,000 scenarios; every scenario ends settled or removed; no level is asked more than 2 times; no repeated text.
- **Used-cost tests:** a used car with no year → age from mileage, never 0; the price criterion uses the used price or no data; depreciation starts from the used price; the warranty is remaining or expired.
- **Architecture test:** ≤ 14 ignore_imports.

## Live check (paid, about €0.05; announce first)

1. `pkill -x automind-api; scripts/dev.sh`
2. In the chat:
   - "Сравни новую Skoda Octavia 2.0 дизель и Audi A4 2.5 б/у 50000 км". Expect the Octavia question "116 CV or 150 CV" with chips (+ "choose for me"), and the A4 year asked once.
   - "2023". Expect "the A4 of 2023 has no 2.5; there is: …" with only the 2023 (B9) engines.
   - "выбери сам". Expect both cars settled, the card shown, no loop.
   - Confirm, and check in the report:
     - the A4 is labelled used (2023, 50,000 km);
     - price used (or no data);
     - value now in depreciation;
     - warranty remaining or expired.
3. A second chat with the Octavia: no new versions search (the usage shows 0 identify searches).
