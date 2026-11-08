"""Relevance rejections later contradicted, and the offline measure of a relevance keyword change (spec 011 US5 gap
"manuales"; constitution XII). Pure.

- `rule_of(reason)`: the relevance rule a stored reason names ("other gearbox: manual (wanted automatic)" →
  `gearbox.manual`), and `LEVER_OF` the declarative keyword list that can loosen it (`relevance.keywords.not_manual`
  for a manual named in the title/URL that is not a gearbox: "manual del vehículo");
- `trigger(rule, title_url)`: the word that fired, with its context in the title/URL (what the auditor clusters on
  and what a stop phrase must contain);
- `contains_value(text, value)`: a confirmed value is written on the page (Spanish and English number formats);
- `stop_phrase_problem(...)`: code's check of the phrase the model suggests (it must contain the trigger word, be more
  specific than the word itself, and occur on the cluster's pages);
- `RelevanceMeasure` / `relevance_verdict`: the replay and shadow decision on pages re-judged with the candidate
  keywords — pages flipped to relevant, the precision of their values against gold/agreement, and the junk guard
  (pages whose values are wrong — correct rejections — must stay rejected).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from automind.acquisition.domain.gates import GateVerdict, Verdict
from automind.acquisition.domain.replay import wilson_lb

REJECTED = ("OTHER_VARIANT", "NOT_ABOUT_CAR")
# the relevance rule of a stored reason → the keyword list that may loosen it (whitelisted lever paths)
LEVER_OF = {
    "gearbox.manual": "relevance.keywords.not_manual",
    "gearbox.automatic": "relevance.keywords.not_auto",
    "drive.AWD": "relevance.keywords.not_awd",
}
_MANUAL = ("manual", "manuell", "manuelle", "mt", "6mt", "5mt", "schaltgetriebe", "handschaltung")
_AUTO = ("dsg", "cvt", "e cvt", "ecvt", "6at", "8at", "steptronic", "tiptronic", "dct", "edc")
_AWD = ("4x4", "awd", "4wd", "quattro", "xdrive", "4motion", "all wheel", "4matic", "integral", "tracción total",
        "traccion total", "allrad")  # fmt: skip


def _alts(words: Sequence[str]) -> list[str]:
    return [re.escape(w) for w in words]


# the words each rule fires on (domain/relevance and domain/sense), as regular expressions
WORDS: dict[str, list[str]] = {
    "gearbox.manual": _alts(_MANUAL),
    "gearbox.automatic": [r"auto(?:mat\w*|m[aá]tic\w*)?", *_alts(_AUTO)],
    "drive.AWD": _alts(_AWD),
}
CONTEXT_WORDS = 2  # words after the trigger kept as its context
MAX_PHRASE_WORDS = 4


def rule_of(verdict: str, reason: str) -> str:
    """A stable rule id of a stored relevance reason."""
    r = (reason or "").lower()
    if verdict == "NOT_ABOUT_CAR":
        return "not_about_car"
    if r.startswith("other gearbox: manual"):
        return "gearbox.manual"
    if r.startswith("other gearbox: automatic"):
        return "gearbox.automatic"
    if r.startswith("other drive: awd"):
        return "drive.AWD"
    if r.startswith("other drive: 2wd"):
        return "drive.2WD"
    head = r.split(":", 1)[0].strip() or "other"
    return re.sub(r"[^a-z0-9]+", "_", head).strip("_")


def title_url(title: str, url: str) -> str:
    """The text the relevance rules read for gearbox and drive words (domain/relevance.judge)."""
    return f"{title}\n{url}".lower().replace("-", " ").replace("_", " ")


def _word_re(w: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(w)}(?!\w)")


def trigger(rule: str, text: str) -> tuple[str, str] | None:
    """(trigger word, context) of the first rule word in a title/URL text: "manual", "manual del vehículo"."""
    words = WORDS.get(rule)
    if not words:
        return None
    t = " ".join(text.lower().split())
    best: tuple[int, str] | None = None
    for w in words:
        m = re.search(rf"(?<!\w)(?:{w})(?!\w)", t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.group(0))
    if best is None:
        return None
    start, w = best
    tail = re.findall(r"[\w'.]+", t[start + len(w):])[:CONTEXT_WORDS]  # fmt: skip
    return w, " ".join([w, *tail]).strip(" .")


def has_phrase(text: str, phrase: str) -> bool:
    return _word_re(" ".join(phrase.lower().split())).search(" ".join(text.lower().split())) is not None


def stop_phrase_problem(phrase: str, word: str, titles: Sequence[str], current: Sequence[str],
                        min_pages: int) -> str | None:  # fmt: skip
    """Why a suggested stop phrase is refused (None = acceptable)."""
    p = " ".join(phrase.lower().split())
    if not _word_re(word).search(p):
        return f"phrase {phrase!r} does not contain the trigger word {word!r}"
    n_words = len(p.split())
    if n_words < 2 or n_words > MAX_PHRASE_WORDS:
        return f"phrase {phrase!r} must have 2 to {MAX_PHRASE_WORDS} words (more specific than {word!r})"
    if p in {" ".join(str(c).lower().split()) for c in current}:
        return f"phrase {phrase!r} is already in the list"
    hits = sum(1 for t in titles if has_phrase(t, p))
    if hits < min_pages:
        return f"phrase {phrase!r} occurs on {hits} of the cluster's pages (at least {min_pages})"
    return None


# --- numbers on a page --------------------------------------------------------------------------------------------

_NUM = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\d.,])\d+(?:[.,]\d+)?(?![\d])")


def numbers(text: str) -> set[float]:
    """Every number a text writes, read both as a decimal and as a thousands group ("1.615" → 1615 and 1.615)."""
    out: set[float] = set()
    for m in _NUM.finditer(text):
        tok = m.group(0).replace(" ", " ")
        compact = tok.replace(" ", "")
        for s in {compact.replace(".", "").replace(",", "."), compact.replace(",", ""),
                  compact.replace(",", "."), compact}:  # fmt: skip
            try:
                out.add(float(s))
            except ValueError:
                continue
    return out


def contains_value(nums: set[float], value: float, rel: float = 0.01) -> bool:
    return any(abs(n - value) <= rel * abs(value) + 1e-9 for n in nums)


# --- clusters -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectedPage:
    """A page a relevance rule rejected for a variant whose values other families later confirmed."""

    snapshot_id: str
    variant_id: str
    url: str
    title: str
    verdict: str
    reason: str
    confirmed: tuple[str, ...]  # attributes the page writes at the confirmed value

    @property
    def rule(self) -> str:
        return rule_of(self.verdict, self.reason)

    @property
    def text(self) -> str:
        return title_url(self.title, self.url)


@dataclass
class RelevanceCluster:
    rule: str
    word: str
    pages: list[RejectedPage] = field(default_factory=list)
    contexts: dict[str, int] = field(default_factory=dict)

    @property
    def path(self) -> str | None:
        return LEVER_OF.get(self.rule)

    @property
    def variants(self) -> list[str]:
        return sorted({p.variant_id for p in self.pages})

    @property
    def reason(self) -> str:
        return self.pages[0].reason if self.pages else self.rule


def relevance_clusters(pages: Sequence[RejectedPage], min_cluster: int) -> list[RelevanceCluster]:
    """Contradicted rejections grouped by (rule, trigger word), largest first; a rule without a word list groups
    under its rule alone (reported, no lever)."""
    by: dict[tuple[str, str], RelevanceCluster] = {}
    for p in pages:
        got = trigger(p.rule, p.text)
        word, ctx = got if got is not None else ("", "")
        c = by.setdefault((p.rule, word), RelevanceCluster(p.rule, word))
        if any(q.snapshot_id == p.snapshot_id for q in c.pages):
            continue
        c.pages.append(p)
        if ctx:
            c.contexts[ctx] = c.contexts.get(ctx, 0) + 1
    out = [c for c in by.values() if len({p.snapshot_id for p in c.pages}) >= min_cluster]
    return sorted(out, key=lambda c: (-len(c.pages), c.rule, c.word))


# --- the offline measure and the gate -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RelevanceGateConfig:
    window_days: int = 30
    max_pages: int = 400
    min_flipped: int = 3
    min_checked: int = 6
    min_precision: float = 0.9
    max_junk_rate: float = 0.05
    max_lost_right: int = 0

    @classmethod
    def from_mapping(cls, agents: Mapping[str, Any] | None) -> RelevanceGateConfig:
        d = cls()
        g = ((agents or {}).get("gates") or {}).get("relevance") or {}
        return cls(**{k: type(getattr(d, k))(g[k]) for k in asdict(d) if g.get(k) is not None})


@dataclass(frozen=True)
class PageCheck:
    """One stored page re-judged with the old and the new keywords; values checked against gold/agreement."""

    snapshot_id: str
    variant_id: str
    old: str
    new: str
    right: int = 0
    wrong: int = 0
    values: int = 0

    @property
    def junk(self) -> bool:
        """Its values are mostly wrong for the variant: rejecting it was right."""
        return self.wrong > self.right

    @property
    def flipped(self) -> bool:
        return self.old in REJECTED and self.new not in REJECTED

    @property
    def lost(self) -> bool:
        return self.old not in REJECTED and self.new in REJECTED


@dataclass(frozen=True)
class RelevanceMeasure:
    pages: int = 0
    rejected_old: int = 0
    flipped: int = 0
    lost: int = 0
    values_checked: int = 0  # values on flipped pages with gold or agreement
    values_right: int = 0
    correct_rejections: int = 0  # rejected pages whose values are wrong
    junk_accepted: int = 0  # of those, flipped by the change
    lost_right: int = 0  # right values on pages the change would newly reject
    unreproduced: int = 0  # stored verdicts the rules no longer give (other context): left out

    @property
    def precision(self) -> float | None:
        return self.values_right / self.values_checked if self.values_checked else None

    @property
    def precision_lb(self) -> float | None:
        return wilson_lb(self.values_right, self.values_checked)

    @property
    def junk_rate(self) -> float:
        return self.junk_accepted / self.correct_rejections if self.correct_rejections else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "precision": self.precision, "precision_lb": self.precision_lb,
                "junk_rate": self.junk_rate}  # fmt: skip

    @classmethod
    def from_pages(cls, checks: Sequence[PageCheck], unreproduced: int = 0) -> RelevanceMeasure:
        flipped = [c for c in checks if c.flipped]
        rejected = [c for c in checks if c.old in REJECTED]
        correct = [c for c in rejected if c.junk]
        return cls(
            pages=len(checks), rejected_old=len(rejected), flipped=len(flipped),
            lost=sum(1 for c in checks if c.lost),
            values_checked=sum(c.right + c.wrong for c in flipped), values_right=sum(c.right for c in flipped),
            correct_rejections=len(correct), junk_accepted=sum(1 for c in correct if c.flipped),
            lost_right=sum(c.right for c in checks if c.lost), unreproduced=unreproduced,
        )  # fmt: skip

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> RelevanceMeasure | None:
        if not d:
            return None
        return cls(**{k: int(d.get(k) or 0) for k in asdict(cls())})


def _guards(m: RelevanceMeasure, cfg: RelevanceGateConfig) -> list[str]:
    bad = []
    if m.values_checked and (m.precision or 0.0) < cfg.min_precision - 1e-9:
        bad.append(f"precision {m.values_right}/{m.values_checked} of the newly accepted values < "
                   f"{cfg.min_precision:.2f}")  # fmt: skip
    if m.junk_rate > cfg.max_junk_rate + 1e-9:
        bad.append(f"junk acceptance {m.junk_accepted}/{m.correct_rejections} correct rejections flipped "
                   f"(> {cfg.max_junk_rate:.0%})")  # fmt: skip
    if m.lost_right > cfg.max_lost_right:
        bad.append(f"{m.lost_right} right values lost on {m.lost} newly rejected pages")
    return bad


def relevance_replay_verdict(m: RelevanceMeasure, cfg: RelevanceGateConfig, *, wait_days: int,
                             waited_days: float = 0) -> Verdict:  # fmt: skip
    """The replay gate of a relevance keyword change: harm is a failure at once; too little evidence waits, then
    the change is abandoned."""
    bad = _guards(m, cfg)
    if bad:
        return Verdict(GateVerdict.FAIL, tuple(bad))
    if m.flipped < cfg.min_flipped or m.values_checked < cfg.min_checked:
        why = (f"{m.flipped} pages flipped (at least {cfg.min_flipped}), {m.values_checked} values checked "
               f"(at least {cfg.min_checked})")  # fmt: skip
        if waited_days >= wait_days:
            return Verdict(GateVerdict.ABANDON, (f"{why} after {wait_days} days",))
        return Verdict(GateVerdict.INSUFFICIENT_EVIDENCE, (why,))
    return Verdict(GateVerdict.PASS, (), ("flipped",))


def relevance_shadow_verdict(m: RelevanceMeasure, cfg: RelevanceGateConfig, *, days: float, min_pages: int,
                             decide_days: float, max_days: float, budget_left: bool = True) -> Verdict:  # fmt: skip
    """The shadow gate on pages judged live since the replay passed: no harm once enough pages are in."""
    if not budget_left:
        return Verdict(GateVerdict.ABANDON, ("the agent's budget ran out during shadow",))
    bad = _guards(m, cfg)
    if bad:
        return Verdict(GateVerdict.FAIL, tuple(bad))
    if not (m.pages >= min_pages or (m.pages > 0 and days >= decide_days)):
        if days >= max_days:
            return Verdict(GateVerdict.ABANDON, (f"{m.pages} shadow pages in {max_days:g} days",))
        return Verdict(GateVerdict.WAIT, (f"{m.pages}/{min_pages} shadow pages",))
    return Verdict(GateVerdict.PASS, (), ("flipped",) if m.flipped else ())


def sentence_part(m: RelevanceMeasure) -> str:
    """The journal's numbers of a relevance measure."""
    return (f"replay flips {m.flipped}/{m.rejected_old} rejected pages to relevant, "
            f"{m.values_right}/{m.values_checked} new values right, junk accepted "
            f"{m.junk_accepted}/{m.correct_rejections}")  # fmt: skip
