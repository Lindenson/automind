"""Line-up sanity (spec 013 T014, D4; owner 2026-11-26): a make's line-up that cannot be its range is never stored
nor used. The Mercedes-Benz ES line-up of chat d170b861 was one model, "Clase S", from a news article about S-Class
prices — and it made "C-Class" an unknown model.

A line-up is accepted when the maker's own site is one of its sources (an official list is the range, however
short), or else when it has at least `min_models` models and they do not all come from one news article (a page whose
address is a headline slug, "…/maldito-dinero-todos-los-precios-del-nuevo-mercedes-benz-clase-s…/": it lists the
models it is about, not the range). A price list of the make ("…/precios/hyundai/") is a range.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from urllib.parse import urlparse

MANUFACTURER = "MANUFACTURER"  # a source's type: the maker's own site
MIN_MODELS = 5  # config/search.yaml intake.lineup_min_models (owner 2026-11-26)
HEADLINE_WORDS = 5  # a path segment of this many hyphenated words is an article's headline
_WORD = re.compile(r"[^\W_]+")


class LineupFault(StrEnum):
    """Why a line-up is not the make's range."""

    TOO_FEW = "too_few_models"
    ONE_ARTICLE = "single_article"


def lineup_fault(model_sources: Iterable[str | None], sources: Iterable[Mapping[str, object]],
                 min_models: int = MIN_MODELS) -> LineupFault | None:  # fmt: skip
    """The fault of a line-up given each model's source URL and the sources read; None when it is sane."""
    if any(str(s.get("type") or "") == MANUFACTURER for s in sources):
        return None
    urls = list(model_sources)
    if len(urls) < min_models:
        return LineupFault.TOO_FEW
    pages = {u for u in urls if u}
    if len(pages) == 1 and is_article(next(iter(pages))):
        return LineupFault.ONE_ARTICLE
    return None


def is_article(url: str) -> bool:
    """The address of a news article: a path segment that is a headline (many hyphenated words)."""
    path = urlparse(url if "//" in url else f"//{url}").path
    return any(len(_WORD.findall(seg)) >= HEADLINE_WORDS and seg.count("-") >= HEADLINE_WORDS - 1
               for seg in path.split("/"))  # fmt: skip
