# WIP: research of cars sold only outside Europe (branch `fix-home-market-research`)

Live chat 2026-11-06 (chat `9c267a3b-…`): "я вот выбираю между Deepal S09 и Lixiang L9 и хочу сделать однозначный
выбор". Both cars were identified on the Chinese market (`CaseCar.market = "CN"`), but the report said for both
"стоимость энергии не посчитать — нет данных: …"; specs 0 accepted values. research_jobs.queries show European sites
only (km77, carwow, autoexpress, autopista, tcs.ch, …) — no Chinese query, no Chinese source.

## Root cause (where the market was dropped)

1. `orchestration/nodes/research.py` built `acquisition.AcquireRequest` without the car's market — the request had
   no field for it.
2. `vehicle_variants.market` is always the default `ES` (`application/resolve.upsert_variant` never sets it), so the
   engine could not recover it either (both live variants: `market = ES`).
3. `acquisition/pipeline/plan.py` planned only `search.yaml` area markets (ES/EN/DE…) and the registry's European
   markets; `job.target_of` told the extractor/validator "market ES", so Chinese pages would be "another market".
4. No CLTC attribute: a Chinese range / kWh/100 km had nowhere correct to go (WLTP only); Chinese units and the
   亏电油耗 words were unknown; relevance did not know Chinese model names (理想L9 has no Latin "l9" word ≥ 3 chars).

## Done (check.sh green: 1436 backend + 161 frontend tests; goldens unchanged)

- `AcquireRequest.market` → `JobSpec.market`; the research node passes `car.market`; the engine also falls back to
  `Variant.market` when it is not European (`plan.home_market`).
- `plan.home_queries` (+ `locate.pages_for` batch with its own page limit): for a non-European market and any area but
  prices (FR-009) — Chinese queries with the local name (`aliases.yaml local_names`: 深蓝S09, 理想L9, …), one `site:`
  query to the registry's CN sources (pcauto/autohome excluded by `abroad.terms_exclude`), one English query to
  carnewschina.com / cnevpost.com. Config: `search.yaml abroad.CN.research`. Terms-excluded sites are never read,
  whichever search found them (`locate.terms_excluded`).
- `target_of` for such a car: "market CN (China; not sold in Europe, sold there as 深蓝S09 …)" + the Chinese label
  glossary (`research.target`), so extractor/validator/relevance treat Chinese pages as the car's own.
- New attributes `range_cltc`, `consumption_ev_cltc` (specs.py, table rows, ELECTRIC_ONLY, ENERGY_INPUTS, TcoCar /
  EnergyCar). `sense_ev.ev_cycle`: a range / kWh/100 km from a Chinese page (CJK excerpt or .cn host) or saying CLTC is
  CLTC, WLTP/WLTC is WLTP, NEDC rejected — never a CLTC figure as WLTP. 亏电/馈电 = charge-sustaining; 加权 = weighted.
  Chinese units (公里, 秒, 千瓦时/百公里, 升/百公里, 公里/小时).
- Energy model: without WLTP figures, CLTC kWh/100 km × and CLTC range ÷ `rates.yaml real_world_factor.CLTC` (1.40),
  labelled "CLTC (China) … (assumption)".
- Relevance: `rel.Target.names` from `Aliases.names_of` (model aliases + local names).
- "Agreed" message: each car not sold in Spain carries `note` ("… в Европе не продаётся — нашёл на рынке Китая") in the
  block and the text; `Agreed.tsx` shows it in the summary line (live it only appeared as notices at the report's end).
- Stage versions bumped: plan@2, locate@2, validate@2, relevance@2.
- Tests: `tests/integration/test_home_market_research.py` (fixtures `tests/fixtures/scenarios/china_research`: d1ev
  S09 and chexun L9 spec tables, carnewschina S09) — CN queries/sources, values filled as CLTC/CS, energy computed,
  no "energy_missing" notice; prices never searched in China; a Spanish car gets no CN search.

## Remains

1. Graph test: intake card → "yes" → the agreed message text/blocks carry the market note, and the research jobs are
   sent with `market="CN"` (stub `ports.acquisition.acquire` to capture the request). Not written yet.
2. Unit tests for `sense_ev.ev_cycle`, the CLTC energy branch, the Chinese units, `Aliases.names_of`.
3. Optional: set `Variant.market` at `upsert_variant` for a non-European car (prefetch worker would then research
   it at home too). electrive.com not added (not in the registry survey; robots/terms not checked).
4. Frontend electric block does not show the CLTC range separately (the spec table rows and the energy inputs do).

## Verify

- `TEST_DATABASE_URL=… scripts/check.sh` (see the task brief), or just
  `uv run pytest tests/integration/test_home_market_research.py tests/integration/test_acquire_facade.py`.
- After deploy, replay the live chat: "я вот выбираю между Deepal S09 и Lixiang L9 и хочу сделать однозначный выбор".
  Expect in research_jobs.queries: `深蓝S09 参数配置 百公里电耗 纯电续航 亏电油耗`, `理想L9 …`,
  `深蓝S09 site:<registry CN sources>`, `Deepal S09 specs CLTC range kWh/100km fuel consumption site:carnewschina.com
  OR site:cnevpost.com`; claims `range_cltc`, `consumption_ev_cltc`, `consumption_cs` accepted; no "нет данных" energy
  notice; the "Договорились" entry says "в Европе не продаётся — нашёл на рынке Китая".
