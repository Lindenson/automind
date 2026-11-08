"""Safety of an address regex in a parser spec (spec 011 contracts/parser-spec.md): anchored, short, and free of the
shapes that backtrack catastrophically. Pure; reads the stdlib's own parse tree, so the check sees what `re` runs."""

from __future__ import annotations

import re
import sys
from typing import Any

# the stdlib's regex parser and opcodes, loaded with `re` (typeshed does not describe these private modules)
_parser = sys.modules["re._parser"]
c = sys.modules["re._constants"]

MAX_PATTERN = 200


def regex_problem(pattern: str) -> str | None:
    """None when `pattern` is a safe anchored address regex (≤ 200 chars, no back-references or nested quantifiers);
    otherwise the problem in a few words ("pattern must be anchored with ^", "nested quantifier", …)."""
    if len(pattern) > MAX_PATTERN:
        return f"pattern longer than {MAX_PATTERN} chars"
    if not pattern.startswith("^"):
        return "pattern must be anchored with ^"
    try:
        tree = _parser.parse(pattern)
    except re.error as e:
        return f"bad regex: {e}"
    return _walk(tree, False)


def _walk(parsed: Any, in_repeat: bool) -> str | None:
    """Catastrophic-backtracking shapes: a repeat inside a repeat, or a back-reference."""
    for op, av in parsed:
        if op in (c.GROUPREF, c.GROUPREF_EXISTS):
            return "back-reference"
        if op in (c.MAX_REPEAT, c.MIN_REPEAT, c.POSSESSIVE_REPEAT):
            _lo, hi, sub = av
            many = hi is c.MAXREPEAT or hi > 1
            if many and in_repeat:
                return "nested quantifier"
            subs, inner = [sub], in_repeat or many
        else:
            subs, inner = _children(op, av), in_repeat
        for sub_pattern in subs:
            if (p := _walk(sub_pattern, inner)) is not None:
                return p
    return None


def _children(op: Any, av: Any) -> list[Any]:
    """The sub-patterns of one node of the stdlib's regex parse tree."""
    if op == c.SUBPATTERN:
        return [av[-1]]
    if op == c.BRANCH:
        return list(av[1])
    if op in (c.ASSERT, c.ASSERT_NOT):
        return [av[1]]
    if op == c.ATOMIC_GROUP:
        return [av]
    return []
