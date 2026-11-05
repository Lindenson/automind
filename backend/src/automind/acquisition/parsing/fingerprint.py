"""Page structure fingerprint (spec 011 US4, research R11). Pure.

For every element in a label position (the first cell of a table row, a `<dt>`, the first child of a `div.row`) whose
text matches a label of the spec (or every one when no labels are given), a shingle `path|label` is taken: the tag
path from the nearest ancestor with an `id` (or up to depth 6), with class names that carry digits or hashes dropped,
and the label with its digits removed. Values never enter the fingerprint, so another car on the same template gives
the same hash; a redesign moves the paths and the labels. `hash` = sha256[:16] of the sorted shingles; similarity is
the Jaccard index of two shingle sets.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

from automind.acquisition.parsing.spec import ParserSpec, norm_label

MAX_DEPTH = 6
MAX_SHINGLES = 200
_BAD_CLASS = re.compile(r"\d|^[a-z]{0,3}-?[0-9a-f]{5,}$|^css-|^sc-|^jsx-")


@dataclass(frozen=True)
class Fingerprint:
    hash: str
    shingles: frozenset[str]


def spec_labels(spec: ParserSpec) -> list[str]:
    return [norm_label(f.label) for f in spec.fields if f.label]


def _step(n: LexborNode) -> str:
    classes = sorted(c for c in (n.attributes.get("class") or "").split() if not _BAD_CLASS.search(c.lower()))
    return n.tag + "".join("." + c for c in classes)


def _path(n: LexborNode) -> str:
    steps: list[str] = []
    cur: LexborNode | None = n
    while cur is not None and cur.tag not in ("html", "body", "-undef", "#document") and len(steps) < MAX_DEPTH:
        if cur.attributes.get("id"):
            steps.append("#" + str(cur.attributes["id"]))
            break
        steps.append(_step(cur))
        cur = cur.parent
    return ">".join(reversed(steps))


def _label_nodes(tree: LexborHTMLParser) -> Iterator[LexborNode]:
    for tr in tree.css("tr"):
        cells = tr.css("th, td")
        if len(cells) >= 2:
            yield cells[0]
    yield from tree.css("dt")
    for row in tree.css("div.row"):
        first = next(row.iter(), None)
        if first is not None:
            yield first


def _norm(text: str) -> str:
    return " ".join(re.sub(r"\d+", " ", norm_label(text)).split())[:60]


def _matches(label: str, labels: Sequence[str]) -> bool:
    return any(label == x or label.startswith(x) for x in labels)


def structure(html: str, labels: Iterable[str] | None = None) -> Fingerprint:
    """The fingerprint of a page; `labels` (normalised spec labels) restricts it to the spec's own rows."""
    tree = LexborHTMLParser(html)
    wanted = [w for w in (_norm(x) for x in labels) if w] if labels is not None else None
    shingles: set[str] = set()
    for node in _label_nodes(tree):
        label = _norm(node.text(strip=True))
        if wanted is not None and not _matches(label, wanted):
            continue
        shingles.add(f"{_path(node)}|{label}")
    kept = frozenset(sorted(shingles)[:MAX_SHINGLES])
    digest = hashlib.sha256("\n".join(sorted(kept)).encode("utf-8")).hexdigest()[:16]
    return Fingerprint(digest, kept)


def similarity(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard index of two shingle sets; two empty sets are the same structure."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)
