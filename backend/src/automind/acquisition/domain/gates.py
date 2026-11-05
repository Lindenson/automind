"""The gates every agent change passes (spec 011 US5, FR-018, research R14). Pure.

1. Replay on stored pages + gold: enough gold (`min_gold`, else `insufficient_evidence` and, after `wait_days`,
   `abandon`); the KPI `accuracy_lb(new) ≥ accuracy_lb(old) − kpi_slack` (on a degraded object — old yield ≈ 0 or
   flagged degraded — the new version's own `accuracy_lb ≥ min_accuracy_lb`); at least one target metric better
   (yield, accuracy, pass rate); guards within tolerance (coverage, cost per value, freshness).
2. Shadow on the next live/prefetch pages: the same criteria once `shadow_min_pages` pages or `shadow_decide_days`
   days are in (the accuracy KPI only with enough gold on those pages: replay proved it); `abandon` on budget or
   `shadow_max_days`.
3. Watch after acceptance: `rollback` on an accuracy_lb drop, a yield drop or enough wrong signals blamed to the new
   version; `keep` after `watch_days`.
`explain()` builds the journal's one sentence with the numbers (code, never a model).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

VerdictKind = Literal["pass", "fail", "insufficient_evidence", "wait", "abandon", "keep", "rollback"]


def _get(m: Mapping[str, Any] | None, *path: str, default: Any = None) -> Any:
    node: Any = m or {}
    for p in path:
        node = node.get(p) if isinstance(node, Mapping) else None
    return default if node is None else node


@dataclass(frozen=True)
class GateConfig:
    min_gold: int = 20
    kpi_slack: float = 0.01
    better_yield: float = 0.05
    better_accuracy: float = 0.02
    better_pass_rate: float = 0.05
    coverage_drop: float = 0.02
    cost_rise: float = 0.10
    min_accuracy_lb: float = 0.8
    wait_days: int = 7
    degraded_yield: float = 0.05  # "old yield ≈ 0"
    shadow_min_pages: int = 20
    shadow_decide_days: float = 3
    shadow_max_days: float = 7
    watch_accuracy_lb_drop: float = 0.03
    watch_yield_drop: float = 0.20
    watch_wrong_signals: int = 3
    watch_days: int = 7

    @classmethod
    def from_mapping(cls, agents: Mapping[str, Any] | None) -> GateConfig:
        """From config/agents.yaml (`gates`, `shadow`, `watch_days`)."""
        d = cls()
        r = ("gates", "replay")
        w = ("gates", "watch")
        return cls(
            min_gold=int(_get(agents, *r, "min_gold", default=d.min_gold)),
            kpi_slack=float(_get(agents, *r, "kpi_slack", default=d.kpi_slack)),
            better_yield=float(_get(agents, *r, "better", "yield", default=d.better_yield)),
            better_accuracy=float(_get(agents, *r, "better", "accuracy", default=d.better_accuracy)),
            better_pass_rate=float(_get(agents, *r, "better", "pass_rate", default=d.better_pass_rate)),
            coverage_drop=float(_get(agents, *r, "guards", "coverage_drop", default=d.coverage_drop)),
            cost_rise=float(_get(agents, *r, "guards", "cost_rise", default=d.cost_rise)),
            min_accuracy_lb=float(_get(agents, *r, "min_accuracy_lb", default=d.min_accuracy_lb)),
            wait_days=int(_get(agents, *r, "wait_days", default=d.wait_days)),
            degraded_yield=float(_get(agents, *r, "degraded_yield", default=d.degraded_yield)),
            shadow_min_pages=int(_get(agents, "shadow", "min_pages", default=d.shadow_min_pages)),
            shadow_decide_days=float(_get(agents, "shadow", "decide_days", default=d.shadow_decide_days)),
            shadow_max_days=float(_get(agents, "shadow", "max_days", default=d.shadow_max_days)),
            watch_accuracy_lb_drop=float(_get(agents, *w, "accuracy_lb_drop", default=d.watch_accuracy_lb_drop)),
            watch_yield_drop=float(_get(agents, *w, "yield_drop", default=d.watch_yield_drop)),
            watch_wrong_signals=int(_get(agents, *w, "wrong_signals", default=d.watch_wrong_signals)),
            watch_days=int(_get(agents, "watch_days", default=d.watch_days)),
        )


@dataclass(frozen=True)
class Metrics:
    """Headline metrics of one version on one corpus (a replay report or accumulated shadow pages)."""

    pages: int = 0
    yield_: float = 0.0  # accepted values per page
    pass_rate: float = 0.0  # accepted / read rows
    gold_covered: int = 0
    gold_match: int = 0
    accuracy_lb: float | None = None  # Wilson lower bound of gold_match / gold_covered
    coverage: float | None = None  # attributes found per variant
    cost_per_value: float | None = None  # EUR per accepted value (model spend; 0 for readers)
    freshness_days: float | None = None

    @property
    def accuracy(self) -> float | None:
        return self.gold_match / self.gold_covered if self.gold_covered else None

    @classmethod
    def from_report(cls, r: Mapping[str, Any] | None) -> Metrics:
        r = r or {}
        opt = {k: (float(r[k]) if r.get(k) is not None else None)
               for k in ("accuracy_lb", "coverage", "cost_per_value", "freshness_days")}  # fmt: skip
        return cls(
            pages=int(r.get("pages") or 0),
            yield_=float(r.get("yield", r.get("yield_")) or 0.0),
            pass_rate=float(r.get("pass_rate") or 0.0),
            gold_covered=int(r.get("gold_covered") or 0),
            gold_match=int(r.get("gold_match") or 0),
            **opt,
        )

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["yield"] = d.pop("yield_")
        d["accuracy"] = self.accuracy
        return d


@dataclass(frozen=True)
class Verdict:
    verdict: VerdictKind
    reasons: tuple[str, ...] = ()
    better: tuple[str, ...] = ()
    degraded: bool = False

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reasons": list(self.reasons), "better": list(self.better),
                "degraded": self.degraded}  # fmt: skip


def _f(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def is_degraded(old: Metrics, cfg: GateConfig, flagged: bool = False) -> bool:
    return flagged or old.yield_ <= cfg.degraded_yield


def _kpi(old: Metrics, new: Metrics, cfg: GateConfig, degraded: bool) -> str | None:
    if degraded or old.accuracy_lb is None:
        if new.accuracy_lb is None or new.accuracy_lb < cfg.min_accuracy_lb:
            return f"accuracy_lb {_f(new.accuracy_lb)} < {cfg.min_accuracy_lb:.2f} (degraded object)"
        return None
    floor = old.accuracy_lb - cfg.kpi_slack
    if new.accuracy_lb is None or new.accuracy_lb < floor - 1e-9:
        return f"accuracy_lb {_f(new.accuracy_lb)} < {floor:.2f} (old {old.accuracy_lb:.2f} − {cfg.kpi_slack:g})"
    return None


def _better(old: Metrics, new: Metrics, cfg: GateConfig) -> tuple[str, ...]:
    out = []
    if new.yield_ - old.yield_ >= cfg.better_yield - 1e-9:
        out.append("yield")
    if new.accuracy is not None and new.accuracy - (old.accuracy or 0.0) >= cfg.better_accuracy - 1e-9:
        out.append("accuracy")
    if new.pass_rate - old.pass_rate >= cfg.better_pass_rate - 1e-9:
        out.append("pass_rate")
    return tuple(out)


def _guards(old: Metrics, new: Metrics, cfg: GateConfig) -> list[str]:
    bad = []
    if old.coverage and new.coverage is not None and new.coverage < old.coverage * (1 - cfg.coverage_drop) - 1e-9:
        bad.append(f"coverage {new.coverage:.2f} vs {old.coverage:.2f} (more than {cfg.coverage_drop:.0%} lower)")
    cost_old, cost_new = old.cost_per_value, new.cost_per_value
    if cost_old and cost_new is not None and cost_new > cost_old * (1 + cfg.cost_rise) + 1e-12:
        bad.append(f"cost per value {cost_new:.5f} vs {cost_old:.5f} EUR (more than {cfg.cost_rise:.0%} higher)")
    if old.freshness_days is not None and new.freshness_days is not None and new.freshness_days > old.freshness_days:
        bad.append(f"freshness {new.freshness_days:.1f} vs {old.freshness_days:.1f} days")
    return bad


def _criteria(old: Metrics, new: Metrics, cfg: GateConfig, degraded: bool, check_kpi: bool = True) -> Verdict:
    reasons = []
    if check_kpi and (k := _kpi(old, new, cfg, degraded)):
        reasons.append(k)
    better = _better(old, new, cfg)
    if not better:
        reasons.append(f"no target metric better (yield {new.yield_:.2f} vs {old.yield_:.2f}, pass rate "
                       f"{new.pass_rate:.2f} vs {old.pass_rate:.2f}, accuracy {_f(new.accuracy)} vs "
                       f"{_f(old.accuracy)})")  # fmt: skip
    reasons += _guards(old, new, cfg)
    return Verdict("fail" if reasons else "pass", tuple(reasons), better, degraded)


def replay_verdict(old: Metrics, new: Metrics, cfg: GateConfig, *, degraded: bool = False,
                   waited_days: float = 0) -> Verdict:  # fmt: skip
    """The replay gate: old and new versions on the same stored pages and gold."""
    deg = is_degraded(old, cfg, degraded)
    if new.gold_covered < cfg.min_gold:
        why = f"{new.gold_covered} gold values covered < {cfg.min_gold}"
        if waited_days >= cfg.wait_days:
            return Verdict("abandon", (f"{why} after {cfg.wait_days} days",), (), deg)
        return Verdict("insufficient_evidence", (why,), (), deg)
    return _criteria(old, new, cfg, deg)


def shadow_verdict(old: Metrics, new: Metrics, cfg: GateConfig, *, days: float, budget_left: bool = True,
                   degraded: bool = False) -> Verdict:  # fmt: skip
    """The shadow gate: both versions on the same live/prefetch pages."""
    deg = is_degraded(old, cfg, degraded)
    if not budget_left:
        return Verdict("abandon", ("the agent's budget ran out during shadow",), (), deg)
    enough = new.pages >= cfg.shadow_min_pages or (new.pages > 0 and days >= cfg.shadow_decide_days)
    if not enough:
        if days >= cfg.shadow_max_days:
            return Verdict("abandon", (f"{new.pages} shadow pages in {cfg.shadow_max_days:g} days",), (), deg)
        return Verdict("wait", (f"{new.pages}/{cfg.shadow_min_pages} shadow pages",), (), deg)
    return _criteria(old, new, cfg, deg, check_kpi=new.gold_covered >= cfg.min_gold)


def watch_verdict(baseline: Metrics, current: Metrics, wrong_signals: int, days: float, cfg: GateConfig) -> Verdict:
    """The watch after acceptance: roll back on degradation, keep after `watch_days`."""
    reasons = []
    if wrong_signals >= cfg.watch_wrong_signals:
        reasons.append(f"{wrong_signals} wrong values blamed to the new version")
    lb0, lb1 = baseline.accuracy_lb, current.accuracy_lb
    if (
        current.pages
        and current.gold_covered
        and lb0 is not None
        and lb1 is not None
        and (lb1 < lb0 - cfg.watch_accuracy_lb_drop - 1e-9)
    ):
        reasons.append(f"accuracy_lb {lb1:.2f} vs {lb0:.2f} at acceptance")
    if current.pages and baseline.yield_ > 0 and current.yield_ < baseline.yield_ * (1 - cfg.watch_yield_drop) - 1e-9:
        reasons.append(f"yield {current.yield_:.2f} vs {baseline.yield_:.2f} at acceptance")
    if reasons:
        return Verdict("rollback", tuple(reasons))
    if days >= cfg.watch_days:
        return Verdict("keep", (f"no degradation in {days:g} days",))
    return Verdict("wait", (f"day {days:g} of {cfg.watch_days}",))


# --- the one-sentence explanation ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    kind: str  # parser | prompt | role_model | rule | source
    key: str  # km77 | extract_specs | extractor | plausibility.… | motor.es
    from_version: str | None
    to_version: str | None
    trigger: str  # "table labels changed on 03.11"
    status: str
    gate: str | None = None  # the gate that rejected or abandoned it
    extra: dict[str, Any] = field(default_factory=dict)


_NOUN = {"parser": "parser", "prompt": "prompt", "role_model": "model", "rule": "", "source": "source"}


def short(version: str | None) -> str:
    """`km77@v5` → `v5`; other version strings unchanged."""
    if version and "@v" in version:
        return "v" + version.rsplit("@v", 1)[1]
    return version or "?"


def _subject(f: Facts) -> str:
    if f.kind == "rule":
        return f"rule {f.key} {f.from_version}→{f.to_version}"
    a, b = (short(f.from_version), short(f.to_version)) if f.kind in ("parser", "prompt") else (
        f.from_version or "none", f.to_version or "?")  # fmt: skip
    return f"{f.key} {_NOUN.get(f.kind, f.kind)} {a}→{b}"


def _gold(f: Facts, replay: Metrics | None) -> str | None:
    if replay is None or not replay.gold_covered:
        return None
    return f"{short(f.to_version)} reproduces {replay.gold_match}/{replay.gold_covered} gold values"


def _days(days: float | None) -> str:
    if days is None:
        return ""
    d = max(1, round(days))
    return f" in {d} day" + ("s" if d != 1 else "")


def explain(f: Facts, *, replay: Metrics | None = None, shadow: tuple[Metrics, Metrics] | None = None,
            verdict: Verdict | None = None, wrong_signals: int = 0, days: float | None = None) -> str:  # fmt: skip
    """One sentence with the numbers, e.g. "km77 parser v4→v5: table labels changed on 03.11; v5 reproduces 48/50
    gold values; shadow yield 0.91 vs 0.42"."""
    if f.status == "rolled_back":
        name = f"{f.key} {_NOUN.get(f.kind, f.kind)}".strip() if f.kind != "rule" else f"rule {f.key}"
        to, prev = short(f.to_version), short(f.from_version)
        if wrong_signals and (verdict is None or any("wrong values" in r for r in verdict.reasons)):
            why = f"{wrong_signals} wrong values blamed to {to}{_days(days)}"
        else:
            why = verdict.reason if verdict is not None else "degraded in watch"
        return f"{name} {to} rolled back: {why}; previous {prev} restored"
    parts: list[str] = []
    if f.status in ("rejected", "abandoned"):
        head = f"{_subject(f)} {f.status} at {f.gate or 'replay'}: {verdict.reason if verdict else 'no reason'}"
        parts.append(head)
    else:
        parts.append(f"{_subject(f)}: {f.trigger}" if f.trigger else _subject(f))
    if g := _gold(f, replay):
        parts.append(g)
    if shadow is not None and f.status not in ("rejected", "abandoned"):
        old, new = shadow
        parts.append(f"shadow yield {new.yield_:.2f} vs {old.yield_:.2f}")
    if f.status == "kept":
        parts.append("kept after the watch")
    return "; ".join(p for p in parts if p).replace("\n", " ")
