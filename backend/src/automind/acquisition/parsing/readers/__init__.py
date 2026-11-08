"""Site readers as data (spec 011 US4): `spec` (ParserSpec, FieldRule, parse/check), `spec_check` and `regex_safety`
(what a proposal must pass), `interpreter` (the fixed reader of a spec), `fingerprint` (page structure for drift),
`registry` (the live `SiteReaders` over `ports`; `tally` counts between flushes), `versions` (a stored version),
`migrate_v1` (today's YAML readers as version 1), `legacy` (the v1 reader, the equivalence test's reference).
Everything here is pure except the registry, which reaches storage only through `ports`."""

__all__: list[str] = [
    "fingerprint", "interpreter", "legacy", "migrate_v1", "ports", "regex_safety", "registry", "spec", "spec_check",
    "tally", "versions",
]  # fmt: skip
