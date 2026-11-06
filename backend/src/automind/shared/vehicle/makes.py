"""Make registry (spec 005 R2, R3): makes sold in Spain, their aliases, transliterations and official sites.

Matching order: alias or transliteration as a whole word → URL domain → fuzzy (WRatio ≥ 85) on single words.
Models are matched against a known list (catalog, config or the make's line-up) on the transliterated text and
on a consonant skeleton, so "атека" finds "Ateca" and "спортейдж" finds "Sportage".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from rapidfuzz import fuzz

from automind.shared.vehicle.identity import sound_key, transliterate_ru

FUZZY_MAKE = 85.0
MODEL_MIN = 72.0
MODEL_MARGIN = 4.0
_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_CJK = re.compile(r"[\u3400-\u9fff]")


def alias_pattern(name: str) -> str:
    """A make's alias as a whole word; a Chinese one is written without spaces ("理想L9"), so it has no word edges."""
    if _CJK.search(name):
        return re.escape(name)
    return rf"(?<![\w]){re.escape(name)}(?![\w])"


@dataclass
class MakeRegistry:
    names: dict[str, str] = field(default_factory=dict)  # lower alias / translit -> canonical make
    sites: dict[str, str] = field(default_factory=dict)  # canonical -> "byd.com/es"
    groups: dict[str, str] = field(default_factory=dict)  # canonical -> parent group
    recent: set[str] = field(default_factory=set)  # canonical makes new in the Spanish market (spec 006)
    homes: dict[str, str] = field(default_factory=dict)  # canonical -> the market it comes from ("CN")
    home_sites: dict[str, str] = field(default_factory=dict)  # canonical -> the maker's site there ("lixiang.com")

    @classmethod
    def from_config(cls, d: Mapping[str, Any]) -> MakeRegistry:
        reg = cls()
        for canon, info in (d.get("makes") or {}).items():
            info = info or {}
            for name in [canon, *(info.get("aliases") or []), *(info.get("translit") or [])]:
                reg.names[str(name).lower()] = canon
            if info.get("es_site"):
                reg.sites[canon] = str(info["es_site"])
            if info.get("group"):
                reg.groups[canon] = str(info["group"])
            if info.get("new_in_market"):
                reg.recent.add(canon)
            if info.get("home"):
                reg.homes[canon] = str(info["home"]).upper()
            if info.get("home_site"):
                reg.home_sites[canon] = str(info["home_site"])
        return reg

    @property
    def makes(self) -> list[str]:
        return sorted(set(self.names.values()))

    def new_in_market(self, make: str | None) -> bool:
        return (self.canonical(make) or make or "") in self.recent

    def site(self, make: str) -> str | None:
        return self.sites.get(self.canonical(make) or make)

    def home(self, make: str | None) -> str | None:
        """The market the make comes from (makes.yaml `home`), None when not recorded."""
        return self.homes.get(self.canonical(make) or make or "")

    def sold_in_spain(self, make: str | None) -> bool:
        """A make of the registry with a Spanish site; a make not in the registry is not known not to be."""
        canon = self.canonical(make)
        return canon is None or canon in self.sites

    def site_on(self, make: str, market: str) -> str | None:
        """The maker's site on a market: the Spanish one in Spain and Europe, `home_site` on its home market."""
        canon = self.canonical(make) or make
        if market in ("ES", "EU"):
            return self.sites.get(canon)
        return self.home_sites.get(canon) if self.homes.get(canon) == market else None

    def canonical(self, make: str | None) -> str | None:
        return self.names.get(make.lower()) if make else None

    def make_of_url(self, url: str) -> str | None:
        host = (urlparse(url if "//" in url else f"//{url}").hostname or "").lower().removeprefix("www.")
        for canon, site in self.sites.items():
            dom = site.split("/", 1)[0].lower().removeprefix("www.")
            if host == dom or host.endswith("." + dom):
                return canon
        return None

    def is_home_page(self, url: str) -> bool:
        """The maker's home or country page (byd.com, byd.com/es): it names the make, not a model."""
        if self.make_of_url(url) is None:
            return False
        path = urlparse(url if "//" in url else f"//{url}").path.strip("/")
        return len([p for p in path.split("/") if p]) <= 1 and len(path) <= 6

    def match_make(self, text: str | None) -> str | None:
        if not text:
            return None
        for u in _URL.findall(text):
            if m := self.make_of_url(u):
                return m
        low = _URL.sub(" ", text.lower())
        # longest alias first, as a whole word ("build your dream", "land rover" before "rover")
        for name in sorted(self.names, key=len, reverse=True):
            if re.search(alias_pattern(name), low):
                return self.names[name]
        words = re.findall(r"[\w&-]{3,}", low)
        best: tuple[float, str] | None = None
        for w in words:
            for name, canon in self.names.items():
                if len(name) < 4:
                    continue
                s = fuzz.ratio(w, name)
                if s >= FUZZY_MAKE and (best is None or s > best[0]):
                    best = (s, canon)
        return best[1] if best else None

    def match_model(self, text: str, known: Iterable[str]) -> str | None:
        """The known model the text names (any script), or None when no model is clearly ahead."""
        t = transliterate_ru(text.lower()).strip()
        tk = sound_key(t)
        n_words = len(t.split())
        scored: list[tuple[float, str]] = []
        for k in set(known):
            kl = k.lower()
            s = max(fuzz.WRatio(t, kl), fuzz.ratio(tk, sound_key(kl)) if tk else 0.0)
            if t == kl or re.search(rf"(?<![\w]){re.escape(kl)}(?![\w])", t):
                s = 100.0 + len(kl) / 100  # the model written as is; the longest wins ("Seal U" over "Seal")
            elif len(kl.split()) == n_words:
                s += 5.0
            scored.append((s, k))
        scored.sort(key=lambda x: -x[0])
        if not scored or scored[0][0] < MODEL_MIN:
            return None
        if len(scored) > 1 and scored[0][0] - scored[1][0] < MODEL_MARGIN and scored[0][0] < 100:
            return None
        return scored[0][1]
