# Quickstart: validating the Report Experience

## Prerequisites
- `scripts/dev.sh` running (Docker Postgres, API on :8000) with a working model key (paid tier).

## 1. Gates
```bash
scripts/check.sh      # includes the sense regression set (2026-11-02 defects) and insights/verdict tests
```

## 2. Golden dialogues (replay, then live)
```bash
cd backend && uv run pytest tests/golden -k "g1[2-8]" -s
uv run pytest tests/golden -m live -k "g1[2-8]" -s
```
- G12 three new SUVs (buyer): verdict card first, a trade-off with numbers, no win below thresholds.
- G13 close cars: "too close to call" and what would tip it.
- G14 missing data: one data panel, "find it" closes a gap and the panel shows the change.
- G15 critique "bad, fill in the Mazda": research runs, the report changes.
- G16 "this is wrong" on the gearbox: re-check, corrected with sources.
- G17 vague first message: 1–3 questions with suggested answers; clear message: none.
- G18 Russian conversation: interface labels in Russian.

## 3. Manual checks
- Compare RAV4 / CX-5 / CR-V (new): engineering section explains e-CVT power-split vs Mazda's
  automatic 6-speed; value retention after 3/5 years per car; manufacturer section per make.
- Phone (375 px): verdict, table and panel readable; no page-level horizontal scroll.
- Rate the report; the rating is stored.
