# Source note (owner, 2026-11-28)

The owner's instruction, verbatim: "все взаимодействия с пользователем покрыть контрактами и улучшить до контрактов
и оттестировать. должно работать как часы. и по моделям и по поиску. нужна корректная логика … информацию которая
должна тебе помочь как организовать стратегию поиска ввиде пирамиды, чтобы не бежать сразу по нижнему слою сайтов в
мелких странах или мелких диллеров а начать с крупняка и важного. затем можно идти за деталями."

The note he attached (a summary from another assistant; its claims were checked in `audit-sources.md` §External —
several did not hold: VehiclesDB has no versions and needs no account; carscatalogue has no data):

- No single free, always-updated API covers every model of every maker in every country.
- Candidates: NHTSA vPIC (free, US); "World Vehicle Database" (carscatalogue, GitHub); @meterapp/vehicle-db (offline
  DB, 23 registries); VehiclesDB (18 national registries, canonical ids `car/<make>/<model>`, CSV/JSON/Parquet/SQLite,
  API, MCP server); JATO Specifications (enterprise, 58 markets); S&P Global Mobility (market analytics).
- Proposed architecture: a unified vehicle database (VehiclesDB as the base catalogue, vPIC, JATO/S&P for trims and
  prices, maker websites to verify current models and generations).
- Keep Model, Generation and Variant/Trim apart, plus `market_availability` (a CX-60 differs in Spain, Japan,
  Australia).
- Open question it raised: every car ever built, or only the current models sold on each market?
