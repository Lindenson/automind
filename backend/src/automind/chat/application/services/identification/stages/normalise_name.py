"""Stage normalise_name: the make and model in the catalogue's spelling (spec 005 R1, R10). A URL in the reply is
classified first: a classifieds site is never read, a maker's home page names the make only, a model page stays
for the resolver (robots respected). The model is then matched to a known one in any script or spelling."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from automind.chat.domain.case import CaseCar
from automind.shared import evidence
from automind.shared.vehicle import makes


def classify_url(car: CaseCar, reg: Any) -> str | None:
    """The note on the URL the person sent: "refused:<host>", "page:<host>" or None (none, or a maker's home page,
    which only names the make)."""
    url = car.constraints.url
    if not url:
        return None
    host = (urlparse(url if "//" in url else f"//{url}").hostname or url).removeprefix("www.")
    if evidence.is_denied(url):
        car.constraints.url = None
        return f"refused:{host}"
    if reg is not None and reg.is_home_page(url):
        car.make = car.make or reg.make_of_url(url)
        car.constraints.url = None
        return None
    return f"page:{host}"


def canonical_make(car: CaseCar, reg: Any) -> None:
    """The make in the registry's spelling, or found in the person's words ("Skoda" / "Škoda": the catalog's)."""
    if reg is None:
        return
    canon = reg.canonical(car.make) if car.make else reg.match_make(car.request_text)
    if canon and _plain(canon) != _plain(car.make):
        car.make = canon


def match_model(car: CaseCar, reg: Any, known: set[str]) -> None:
    """The model in any script or spelling, mapped to a known one ("атека" → Ateca, "сил ю" → Seal U)."""
    if reg is None or not known or not car.make:
        return
    if not car.model:
        aliases = [n for n, c in reg.names.items() if c == car.make]
        rest = _strip_make(car.request_text, car.make, aliases)
        if rest and (m := reg.match_model(rest, known)):
            car.model = m
    elif car.model not in known and (m := reg.match_model(car.model, known)):
        car.model = m


def _plain(s: str | None) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _strip_make(text: str, make: str, aliases: list[str]) -> str:
    low = text
    for a in sorted({make.lower(), *aliases}, key=len, reverse=True):
        low = re.sub(makes.alias_pattern(a), " ", low, flags=re.IGNORECASE)
    return " ".join(low.split())
