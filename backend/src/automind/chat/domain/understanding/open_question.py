"""The open bot question as the understanding step sees it (spec 013 T031, understanding-spec §4 "Требование к
Pending"): an id, what was asked, and the options with ids. Pure.

The id is a content hash of the stored `Pending` (its kind and items), so a pending saved before S3 gets the same
stable id on every read and the case file is not changed. Option ids are the ids the chips already send (S1,
`intake.option_ids`; confirmations: `option:<car>:<variant>`, `choose`, card `yes|stop`, cost `run|skip`, research
limit `continue|stop`). S4 (T046) builds the chips from these options, so a chip and the model see one list.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from automind.chat.domain.case import Pending
from automind.chat.domain.intake.option_ids import CAR_KINDS, CHOOSABLE_KINDS, OptionKind, option_id
from automind.chat.domain.understanding.intent import AnswerKind, PendingAnswer


class OpenKind(StrEnum):
    """What kind of question is open: the stored pending's kind, or the research limit (an interrupt)."""

    QUESTIONS = "QUESTIONS"
    CONFIRM_VARIANTS = "CONFIRM_VARIANTS"
    CONFIRM_COST = "CONFIRM_COST"
    CONFIRM_INTAKE = "CONFIRM_INTAKE"
    LIMIT = "LIMIT"


class Asked(StrEnum):
    """The question items whose options are not a list of choices."""

    CONDITION = "CONDITION"
    PROPOSE = "PROPOSE"
    GEARBOX = "GEARBOX"
    ENGINE = "ENGINE"


_ASKED = {a.value: a for a in Asked}
_CONFIRM_TEXT = {
    OpenKind.CONFIRM_VARIANTS: "Is this the version you mean?",
    OpenKind.CONFIRM_COST: "Run the research at this cost?",
    OpenKind.CONFIRM_INTAKE: "Is the card right? Confirm to start the research.",
    OpenKind.LIMIT: "The research limit is reached. Continue?",
}
_YES_NO = {  # (yes id, label), (no id, label)
    OpenKind.CONFIRM_COST: (("run", "yes, run it"), ("skip", "no")),
    OpenKind.CONFIRM_INTAKE: (("yes", "yes, research"), ("stop", "no")),
    OpenKind.LIMIT: (("continue", "continue"), ("stop", "stop")),
}


class QuestionOption(BaseModel):
    """One offered answer: its id (what a chip sends) and its label."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    means: AnswerKind | None = None  # yes / no: the option agrees or refuses (a yes/no question, a proposal)


class OpenQuestion(BaseModel):
    """The question the bot left open: id, kind, the words asked, the cars it concerns and the options."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: OpenKind
    question: str
    cars: tuple[str, ...] = ()
    options: tuple[QuestionOption, ...] = Field(default=())

    def option(self, oid: str | None) -> QuestionOption | None:
        """The option with id `oid`, None when it is not offered."""
        return next((o for o in self.options if o.id == oid), None)


def canonical_answer(a: PendingAnswer | None, q: OpenQuestion | None) -> PendingAnswer | None:
    """One form for "yes" and "no": an option that agrees or refuses is the answer yes / no with its id, and a typed
    yes / no names the one option of that meaning (the policy reads one kind; the record shows the button)."""
    if a is None or q is None or a.pending_id != q.id:
        return a
    if a.kind is AnswerKind.OPTION:
        o = q.option(a.option_id)
        return a if o is None or o.means is None else a.model_copy(update={"kind": o.means})
    same = [o.id for o in q.options if o.means is a.kind]
    return a.model_copy(update={"option_id": same[0]}) if a.option_id is None and len(same) == 1 else a


def pending_id(p: Pending) -> str:
    """The stable id of a stored pending: `q-` and the first 12 hex digits of the sha256 of its canonical JSON."""
    text = json.dumps(p.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "q-" + hashlib.sha256(text.encode()).hexdigest()[:12]


def open_question(p: Pending | None) -> OpenQuestion | None:
    """The open question of a case's pending (None: nothing open)."""
    if p is None:
        return None
    kind = OpenKind(p.kind)
    if kind is OpenKind.QUESTIONS:
        return _questions(p)
    if kind is OpenKind.CONFIRM_VARIANTS:
        return _variants(p)
    return _yes_no(pending_id(p), kind, _cars(p))


def limit_question(question_id: str, text: str | None = None) -> OpenQuestion:
    """The research-limit question (an interrupt of the research, not a stored pending) under `question_id`."""
    return _yes_no(question_id, OpenKind.LIMIT, (), text)


def _questions(p: Pending) -> OpenQuestion:
    texts: list[str] = []
    options: list[QuestionOption] = []
    chooses = False
    for item in p.items:
        kind, car = str(item.get("kind") or ""), str(item.get("car") or "")
        if isinstance(item.get("text"), str) and item["text"] not in texts:
            texts.append(str(item["text"]))
        options += _item_options(kind, car, item)
        chooses = chooses or kind in CHOOSABLE_KINDS or (_ASKED.get(kind) is Asked.ENGINE and bool(item.get("choices")))
    if chooses:
        options.append(QuestionOption(id=OptionKind.CHOOSE.value, label="choose for me"))
    options += [QuestionOption(id=option_id(OptionKind.REMOVE, car), label=f"remove {car}")
                for car in _cars(p, CAR_KINDS)]  # fmt: skip
    return OpenQuestion(id=pending_id(p), kind=OpenKind.QUESTIONS, question=" ".join(texts), cars=_cars(p),
                        options=_unique(options))  # fmt: skip


def _item_options(kind: str, car: str, item: Mapping[str, object]) -> list[QuestionOption]:
    """The options of one question item, with the ids its chips carry."""
    asked = _ASKED.get(kind)
    if asked is Asked.CONDITION:
        return [QuestionOption(id=option_id(OptionKind.CONDITION, c), label=c.lower()) for c in ("NEW", "USED")]
    if not car:
        return []
    if asked is Asked.PROPOSE:
        yes, no = option_id(OptionKind.YES, car), option_id(OptionKind.NO, car)
        return [QuestionOption(id=yes, label="yes", means=AnswerKind.YES),
                QuestionOption(id=no, label="no, another one", means=AnswerKind.NO)]  # fmt: skip
    choices = item.get("choices")
    if isinstance(choices, list) and choices:
        return [QuestionOption(id=option_id(OptionKind.CHOICE, car, kind, n), label=_label(ch))
                for n, ch in enumerate(choices)]  # fmt: skip
    if asked is Asked.GEARBOX:
        return [QuestionOption(id=option_id(OptionKind.GEARBOX, car, g), label=g) for g in ("automatic", "manual")]
    return []


def _variants(p: Pending) -> OpenQuestion:
    options = [QuestionOption(id=str(o.get("id")), label=str(o.get("label") or o.get("id")))
               for item in p.items for o in _dicts(item.get("options"))]  # fmt: skip
    options.append(QuestionOption(id=OptionKind.CHOOSE.value, label="choose for me"))
    kind = OpenKind.CONFIRM_VARIANTS
    return OpenQuestion(id=pending_id(p), kind=kind, question=_CONFIRM_TEXT[kind], cars=_cars(p),
                        options=_unique(options))  # fmt: skip


def _yes_no(qid: str, kind: OpenKind, cars: tuple[str, ...], text: str | None = None) -> OpenQuestion:
    (yes, yes_label), (no, no_label) = _YES_NO[kind]
    options = (QuestionOption(id=yes, label=yes_label, means=AnswerKind.YES),
               QuestionOption(id=no, label=no_label, means=AnswerKind.NO))  # fmt: skip
    return OpenQuestion(id=qid, kind=kind, question=text or _CONFIRM_TEXT[kind], cars=cars, options=options)


def _cars(p: Pending, kinds: tuple[str, ...] | None = None) -> tuple[str, ...]:
    out: list[str] = []
    for item in p.items:
        car = str(item.get("car") or "")
        if car and car not in out and (kinds is None or str(item.get("kind") or "") in kinds):
            out.append(car)
    return tuple(out)


def _label(choice: object) -> str:
    return str(choice.get("label") or "") if isinstance(choice, dict) else str(choice)


def _dicts(value: object) -> list[dict[str, object]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _unique(options: list[QuestionOption]) -> tuple[QuestionOption, ...]:
    """The options without a repeated id, the first kept."""
    first: dict[str, QuestionOption] = {}
    for o in options:
        first.setdefault(o.id, o)
    return tuple(first.values())
