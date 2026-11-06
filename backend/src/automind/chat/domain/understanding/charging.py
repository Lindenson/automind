"""Home charging and the electricity price from the person words (spec 006)."""

from __future__ import annotations

import re

_CHARGE_NO = (r"на улице", r"нет гаража", r"без гаража", r"не могу заряжать дома", r"негде заряжать",
              r"no garage", r"street parking", r"park on the street", r"can'?t charge at home", r"no home charging",
              r"no tengo garaje", r"sin garaje", r"aparco en la calle", r"no puedo cargar en casa",
              r"en la calle")  # fmt: skip


_CHARGE_WORK = (r"на работе", r"charge at work", r"at work", r"en el trabajo", r"cargo en la oficina")


_CHARGE_YES = (r"гараж", r"розетк", r"wallbox", r"вол+бокс", r"заряжа\w* дома", r"зарядк\w* дома",
               r"charge at home", r"charging at home", r"home charger", r"garage", r"driveway",
               r"garaje", r"cargador en casa", r"cargar en casa", r"punto de carga",
               r"plaza de parking propia")  # fmt: skip


_NIGHT = (r"ночь", r"ночн", r"night", r"noche", r"nocturn", r"valle", r"off-?peak")


_FREE = (r"бесплатн", r"for free", r"free", r"gratis")


_PRICE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(€|eur|евро|euros?|c(?:ts?|ent(?:s|imos?)?)?|ц(?:ент\w*)?|céntimos?)\s*"
    r"(?:/|за|per|el|por|a)?\s*(?:1\s*)?(kwh|квт|кв·ч|квт·ч|квтч)",
    re.IGNORECASE,
)


def any_match(patterns: tuple[str, ...], low: str) -> str | None:
    for p in patterns:
        if m := re.search(p, low):
            return m.group(0)
    return None


def charging_of(text: str | None) -> tuple[str, str] | None:
    """(YES | WORK | NO, the words) when the user says where they can charge; "no garage" wins over "garage"."""
    if not text:
        return None
    low = text.lower()
    for value, pats in (("NO", _CHARGE_NO), ("WORK", _CHARGE_WORK), ("YES", _CHARGE_YES)):
        if (w := any_match(pats, low)) is not None:
            return value, w
    return None


MAX_EUR_PER_KWH = 1.5  # above this a stated electricity price is a unit error (cents read as euros)


def electricity_price_of(text: str | None) -> tuple[float, bool] | None:
    """(€/kWh, night tariff?) from "плачу 12 центов за кВт·ч ночью" or "0,09 €/kWh en valle"; free charging
    at work is 0. None when no price is stated or it is not plausible."""
    if not text:
        return None
    low = text.lower()
    night = any_match(_NIGHT, low) is not None
    if m := _PRICE.search(low):
        v = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        if unit[0] in ("c", "ц"):
            v /= 100
        return (round(v, 4), night) if 0 <= v <= MAX_EUR_PER_KWH else None
    if any_match(_FREE, low) and any_match(_CHARGE_WORK, low):
        return 0.0, False
    return None
