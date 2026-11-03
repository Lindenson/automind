# Quickstart: Validating 005 (Intake and Identification)

## Prerequisites

- Docker Postgres on port 5433 with migration 0008 applied (`cd backend && uv run alembic upgrade head`).
- `.env` with the keys, as for 004. Never print the keys.
- `scripts/check.sh` must be green before the scenarios below.

## 1. Pure core (no network, no model)

```bash
cd backend && uv run pytest tests/unit/test_intake.py tests/unit/test_engine_parse.py \
  tests/unit/test_transliteration.py tests/unit/test_makes.py tests/unit/test_rank_lineup.py \
  tests/unit/test_questions_i18n.py -q
```

Expected:
- `parse_engine("Ateca 1.5 двигатель")` → displacement 1.5;
- "1-2 тыс км в месяц" → 12,000–24,000 km/year;
- "сеат атека" → SEAT Ateca;
- every question template exists in en/ru/es, with no empty-option fallback;
- `next_step` never returns the same question hash twice in a row, and proposes after 2 attempts.

## 2. Graph with fakes

```bash
uv run pytest tests/graph/test_identify_loop.py tests/graph/test_corrections.py \
  tests/graph/test_intake_card.py tests/graph/test_no_general_in_intake.py -q
```

Expected:
- **Incident replay**: "BYD Seal U" is identified from the fake line-up.
- **Correction**: "1.5, not 1.0" clears the Ateca 1.0 variant and the card shows 1.0 → 1.5.
- **Brand explanation**: a brand explanation while a question is pending gets no `general` reply.
- **Research gate**: research jobs exist only after the card's "yes".

## 3. Golden replay G21–G30

```bash
uv run pytest tests/golden -k "g2[1-9] or g30" -q
```

Every golden asserts:
- no repeated question;
- a confirmed identity within ≤ 3 user replies;
- the engine on the card equals the user's;
- every message in the conversation language;
- no greeting after the first turn.

## 4. Manual check (paid model and search: announce the estimate first)

Run it on the dev server (:8000) or Docker (:8080) in a new chat. Send the incident message (in Russian):

> скажи насколько хороша byd — найди соответствующую модель — в сравнении с сеат атека… для долгосрочной семейной эксплуатации на юге испании, 1-2 тыс км в месяц, город и трасса, экономить и чтобы не ломалась, приятные ощущения для водителя

Expected:
1. For BYD, the assistant offers 1–3 concrete BYD models on sale in Spain, each with a reason. For example, Seal U DM-i is a family SUV with a plug-in hybrid. It also asks "new or used?" once for both cars.
2. The reply "BYD Seal U" identifies the car. Then "Ateca 1.5" switches the Ateca to the 1.5 TSI and shows "1.0 → 1.5".
3. One card lists both cars and the profile: family, 12,000–24,000 km/year, south of Spain with a hot climate, priorities. Research starts only after "yes".
4. All text is in Russian. There is no greeting mid-dialogue, and no model is shown that the user did not name unless it is marked as a suggestion.

## 5. Metrics

`GET /api/v1/metrics` reports `intake.replies_to_confirmed` (median ≤ 3), `intake.repeated_questions` (0) and `intake.research_unconfirmed` (0).
