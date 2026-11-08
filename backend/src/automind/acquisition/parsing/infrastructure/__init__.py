"""The parsing area's storage and wiring: `parser_store` (parser versions: running, streaks, degrade), `reading_log`
(site counts, snapshot stamps), `v1_specs` (the YAML v1 specs, the deny-list, the seed), `wiring` (the live readers).
Every SQL of the area is here; errors leave as `readers.ports.ParserStoreUnavailable`."""

__all__: list[str] = ["parser_store", "reading_log", "v1_specs", "wiring"]
