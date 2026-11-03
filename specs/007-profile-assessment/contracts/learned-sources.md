# Contract: learned sources

## Update (after every research run, application/learned_sources.update)

Input: the run's jobs. Each job carries area, market, the domains searched (from hits) and the domains of accepted claims.

For each (domain, area, market):
- accepted in this run → `accepted_runs += 1, misses = 0, last_seen = now`;
- searched but nothing accepted → `misses += 1` (only for rows that already exist).

New rows are created only from accepted claims.

## Use (round 0)

`search_plan.queries(..., learned=[...])` appends active learned domains for (area, market) after the configured favourites. There are at most `learned.per_area` of them, in one extra `site:` group with kind `FAVOURITE` and a `learned: true` flag in the planned query (metrics).

## Metrics (`GET /api/v1/research/metrics`)

The response gains two fields:
- `learned_sources: [{domain, area, market, source_type, accepted_runs, misses, active}]`;
- `empty_search_share: {area: {market: share}}`, computed over the last 30 days of `search_calls`.

## Config (`search.yaml`)

```yaml
empty_result_ttl_hours: 6
favourite_retry: true
learned: {min_runs: 3, max_misses: 5, per_area: 4}
```
