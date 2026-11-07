"""The person's own consumption figures ("в гибридном режиме 5,5 л"), each tied to the car named before it in the same
sentence (or left to the one car it can apply to)."""

from __future__ import annotations

import re

from automind.chat.domain import understanding
from automind.chat.domain.case import CaseFile, StatedEnergy
from automind.shared.contracts.config import MakeNames

_SENTENCE_END = re.compile(r"[.!?\n]")  # "… 5,5 л. А у Kia 7" — a figure belongs to its own sentence
_NAME = re.compile(r"[\w&-]{2,}")  # a word that can name a make or a model: "kia", "b&w", "seal-u"
MIN_MODEL_CHARS = 3  # shorter words never name a model ("Li" is a make)
_UNITS = {"FUEL": "l/100 km", "CS": "l/100 km with an empty battery", "KWH": "kWh/100 km",
          "RANGE": "km on electricity"}  # fmt: skip


def energy_from_text(new: CaseFile, text: str, makes: MakeNames | None) -> list[str]:
    """Adds each figure to `new.stated_energy` (in place); the newest figure per car and kind wins. Returns the change
    log."""
    log: list[str] = []
    prev = 0
    for f in understanding.energy_figures_of(text):
        sentence = max((m.end() for m in _SENTENCE_END.finditer(text, 0, f.start)), default=0)
        key = _car_named(new, text[max(prev, sentence) : f.start], makes)
        prev = f.start
        item = StatedEnergy(kind=f.kind, value=f.value, words=f.words, car_key=key)
        new.stated_energy = [x for x in new.stated_energy if (x.kind, x.car_key) != (f.kind, key)] + [item]
        log.append(f'your figure{" for " + key if key else ""}: {f.value:g} {_UNITS[f.kind]} ("{f.words}")')
    return log


def _car_named(case: CaseFile, segment: str, makes: MakeNames | None) -> str | None:
    """The key of the case car the words name (make or model, any script), the last one named; None if none."""
    if makes is None:
        return None
    found: str | None = None
    models = [c.model for c in case.cars if c.model]
    for w in _NAME.findall(segment):
        make = makes.match_make(w)
        model = makes.match_model(w, models) if models and len(w) >= MIN_MODEL_CHARS else None
        for car in case.cars:
            if (model and car.model == model) or (make and car.make == make and not model):
                found = car.key
                if model:
                    break
    return found
