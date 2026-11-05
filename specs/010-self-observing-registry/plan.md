# Implementation Plan: Self-Observing AutoMind and an Autonomous Source Registry

**Branch**: `010-self-observing-registry` | **Date**: 2026-11-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-self-observing-registry/spec.md`

## Summary

Three additions, each behind its own boundary, none slowing a turn:

1. **Observation + Prometheus base**: migration 0014, `relation`, `domain/outcome.py`, runner hooks, `feedback` (+ bad-source button), llm_calls columns; live counters at the same write points; `/metrics`; snapshot gauges and loop heartbeats.
2. **Insight + Top problems**: migration 0015, clusters, impact, issues with proposed fix (code/config via declared levers), regression reopen, seed of 009 issues; `/admin` shell + Top problems screen.
3. **Prometheus rules**: `deploy/prometheus/*`, rules test, optional `monitoring` compose profile.
4. **Registry, same behaviour**: migration 0016, seed, port, research rerouted, `registry.autonomy: false`; goldens unchanged.
5. **Registry autonomy**: score, lifecycle, review loop, discovery + admission, journal, revert/freeze/block, Sources screen, source gauges; flag on.

## Complexity Tracking

None.
