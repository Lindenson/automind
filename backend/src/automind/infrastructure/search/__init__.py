"""Web search (spec 003 R1–R3): interchangeable providers behind a cache-first Searcher."""

from __future__ import annotations


class SearchUnavailable(RuntimeError):
    """The provider cannot answer (no key, no credit, rate limit, server error)."""


__all__ = ["SearchUnavailable"]
