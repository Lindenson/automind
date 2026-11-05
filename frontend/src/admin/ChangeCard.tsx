/** Spec 011 T118 (US6): one journalled change — the diff (JSON for specs and rules, unified for prompts), reason,
 * evidence, gate results with old/new metrics, metrics before/after, the watch chart; Revert, Reject, Forbid similar. */
import { useEffect, useId, useRef, useState } from "react";
import { cx, fmtNum, useEscape } from "../lib/util";
import { LineChart, type Series } from "./charts";
import { ChangeStatusBadge, OriginBadge, fromTo } from "./Changes";
import { Section } from "./ParserCard";
import type { JournalChangeDetail } from "./schemas";
import { BTN_SM, when } from "./Sources";
import { useAdmin } from "./store";

const BTN =
  "rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-panel2 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";
const PRE = "max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-panel2 p-2 font-mono text-xs";
const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 align-top";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

/** A short text of any value: numbers rounded, objects as compact JSON. */
export function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmtNum(v, 4);
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** A unified diff (prompts): + lines green, - lines red. */
export function UnifiedDiff({ text }: { text: string }) {
  return (
    <pre className={PRE} aria-label="Unified diff">
      {text.split("\n").map((line, i) => (
        <span
          key={i}
          className={cx(
            "block",
            line.startsWith("+") && !line.startsWith("+++") && "bg-good/15 text-good",
            line.startsWith("-") && !line.startsWith("---") && "bg-bad/15 text-bad",
            line.startsWith("@@") && "text-accent2",
          )}
        >
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

function Rows({ rows, head }: { rows: [string, unknown, unknown][]; head: [string, string, string] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line/70">
      <table className="w-full text-sm">
        <thead className="bg-panel2/60">
          <tr>
            {head.map((h) => (
              <th key={h} scope="col" className={TH}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, a, b]) => (
            <tr key={k} className="border-t border-line/60">
              <td className={cx(TD, "font-mono text-xs")}>{k}</td>
              <td className={cx(TD, "break-all text-bad")}>{show(a)}</td>
              <td className={cx(TD, "break-all text-good")}>{show(b)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Rows (key, before, after) of a JSON diff: `{before, after}`, JSON patch ops, or `{key: [old, new]}`. */
export function diffRows(diff: unknown): [string, unknown, unknown][] | null {
  if (isObj(diff) && isObj(diff.before) && isObj(diff.after)) {
    const before = diff.before;
    const after = diff.after;
    return [...new Set([...Object.keys(before), ...Object.keys(after)])]
      .filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]))
      .map((k) => [k, before[k], after[k]]);
  }
  const ops = Array.isArray(diff) ? diff : isObj(diff) && typeof diff.op === "string" ? [diff] : null;
  if (ops && ops.every(isObj)) {
    return (ops as Obj[]).map((o) => [`${String(o.op)} ${String(o.path ?? "")}`, o.from ?? o.old ?? null, o.value ?? null]);
  }
  if (isObj(diff)) {
    return Object.entries(diff).map(([k, v]) =>
      Array.isArray(v) && v.length === 2 ? [k, v[0], v[1]] : ([k, null, v] as [string, unknown, unknown]),
    );
  }
  return null;
}

export function DiffView({ diff }: { diff: unknown }) {
  if (typeof diff === "string") return <UnifiedDiff text={diff} />;
  if (isObj(diff) && typeof diff.unified === "string") return <UnifiedDiff text={diff.unified} />;
  const rows = diffRows(diff);
  if (rows && rows.length > 0) return <Rows rows={rows} head={["Field", "Before", "After"]} />;
  return <pre className={PRE}>{JSON.stringify(diff ?? {}, null, 2)}</pre>;
}

/** Gate results: verdict, old vs new metrics, the other facts of each gate. */
export function GatesView({ gates }: { gates: Obj | null }) {
  if (!gates || Object.keys(gates).length === 0) return <p className="text-sm text-muted">No gates (applied at once).</p>;
  return (
    <ul className="space-y-2">
      {Object.entries(gates).map(([name, g]) => {
        const gate = isObj(g) ? g : { value: g };
        const old = isObj(gate.metrics_old) ? gate.metrics_old : {};
        const neu = isObj(gate.metrics_new) ? gate.metrics_new : {};
        const keys = [...new Set([...Object.keys(old), ...Object.keys(neu)])];
        const facts = Object.entries(gate).filter(([k]) => !["verdict", "metrics_old", "metrics_new"].includes(k));
        const verdict = typeof gate.verdict === "string" ? gate.verdict : null;
        return (
          <li key={name} className="space-y-1 rounded-lg border border-line/70 p-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-semibold">{name}</span>
              {verdict && (
                <span className={cx("chip text-[11px]", verdict === "pass" ? "text-good" : verdict === "fail" ? "text-bad" : "")}>
                  {verdict}
                </span>
              )}
              {facts.map(([k, v]) => (
                <span key={k} className="text-xs text-muted">
                  {k}: {show(v)}
                </span>
              ))}
            </div>
            {keys.length > 0 && <Rows rows={keys.map((k) => [k, old[k], neu[k]])} head={["Metric", "Old", "New"]} />}
          </li>
        );
      })}
    </ul>
  );
}

function snapshotRefs(ev: Obj): { id: string; url: string | null }[] {
  const raw = Array.isArray(ev.snapshots) ? ev.snapshots : [];
  return raw.map((x) =>
    isObj(x) ? { id: String(x.id ?? ""), url: typeof x.url === "string" ? x.url : null } : { id: String(x), url: null },
  );
}

export function EvidenceView({ evidence }: { evidence: Obj }) {
  const snaps = snapshotRefs(evidence);
  const rest = Object.fromEntries(Object.entries(evidence).filter(([k]) => k !== "snapshots"));
  if (snaps.length === 0 && Object.keys(rest).length === 0) return <p className="text-sm text-muted">No evidence.</p>;
  return (
    <div className="space-y-2">
      {snaps.length > 0 && (
        <ul className="space-y-0.5 text-xs">
          {snaps.map((s) => (
            <li key={s.id} className="break-all">
              snapshot <code className="font-mono">{s.id}</code>
              {s.url && (
                <>
                  {" — "}
                  <a href={s.url} target="_blank" rel="noreferrer noopener" className="text-accent2 hover:underline">
                    {s.url}
                  </a>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {Object.keys(rest).length > 0 && <pre className={PRE}>{JSON.stringify(rest, null, 2)}</pre>}
    </div>
  );
}

/** Per-day watch metrics of the experiment (`acq_experiments.daily`: a list of days or a map day → metrics). */
export function watchSeries(experiment: Obj | null): { days: string[]; series: Series[] } | null {
  const daily = experiment?.daily;
  const rows: Obj[] = Array.isArray(daily)
    ? daily.filter(isObj)
    : isObj(daily)
      ? Object.entries(daily).map(([day, v]) => ({ day, ...(isObj(v) ? v : { value: v }) }))
      : [];
  if (rows.length === 0) return null;
  const days = rows.map((r, i) => String(r.day ?? i + 1));
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r).filter((k) => k !== "day" && typeof r[k] === "number")))];
  return { days, series: keys.map((k) => ({ label: k, values: rows.map((r) => (typeof r[k] === "number" ? (r[k] as number) : null)) })) };
}

const FORBID_DAYS: [string, number | null][] = [
  ["7 days", 7],
  ["30 days", 30],
  ["90 days", 90],
  ["until lifted", null],
];

export function ChangeActions({
  c,
  saving,
  onRevert,
  onReject,
  onForbid,
}: {
  c: JournalChangeDetail;
  saving: boolean;
  onRevert?: () => void;
  onReject?: () => void;
  onForbid?: (days: number | null) => void;
}) {
  const [days, setDays] = useState("1");
  const id = useId();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {c.revertible && (
          <button type="button" className={cx(BTN, "border-warn/50 text-warn")} disabled={saving} onClick={onRevert}>
            Revert
          </button>
        )}
        {c.rejectable && (
          <button type="button" className={BTN} disabled={saving} onClick={onReject}>
            Reject
          </button>
        )}
        <label htmlFor={id} className="text-xs text-muted">
          Forbid similar for
        </label>
        <select
          id={id}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          className="rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        >
          {FORBID_DAYS.map(([label], i) => (
            <option key={label} value={String(i)}>
              {label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={BTN}
          disabled={saving}
          onClick={() => onForbid?.(FORBID_DAYS[Number(days)]?.[1] ?? null)}
        >
          Forbid similar
        </button>
      </div>
      <p className="text-xs text-muted">
        Revert puts the object back as it was before. Forbid similar freezes the object: no agent may change it.
      </p>
    </div>
  );
}

export function ChangeDetailView({
  c,
  saving = false,
  onRevert,
  onReject,
  onForbid,
}: {
  c: JournalChangeDetail;
  saving?: boolean;
  onRevert?: () => void;
  onReject?: () => void;
  onForbid?: (days: number | null) => void;
}) {
  const watch = watchSeries(c.experiment);
  const before = c.metrics_before ?? {};
  const after = c.metrics_after ?? {};
  const metricKeys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <p className="break-words text-base font-medium">{c.explanation || "—"}</p>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <OriginBadge origin={c.origin} />
          <ChangeStatusBadge status={c.status} />
          <span>{when(c.created_at)}</span>
          {c.author && <span>by {c.author}</span>}
          <span className="font-mono">{fromTo(c)}</span>
          {c.cost_eur > 0 && <span>€{fmtNum(c.cost_eur, 4)}</span>}
        </div>
      </div>
      <ChangeActions c={c} saving={saving} onRevert={onRevert} onReject={onReject} onForbid={onForbid} />
      {c.reason && (
        <Section title="Reason">
          <p className="text-sm">{c.reason}</p>
        </Section>
      )}
      <Section title="Diff">
        <DiffView diff={c.diff} />
      </Section>
      <Section title="Gates">
        <GatesView gates={c.gates} />
      </Section>
      {metricKeys.length > 0 && (
        <Section title="Metrics before / after">
          <Rows rows={metricKeys.map((k) => [k, before[k], after[k]])} head={["Metric", "Before", "After"]} />
        </Section>
      )}
      {watch && (
        <Section title="Watch by day">
          <LineChart label="Watch metrics by day" days={watch.days} series={watch.series} min0={false} />
        </Section>
      )}
      <Section title="Evidence">
        <EvidenceView evidence={c.evidence} />
      </Section>
    </div>
  );
}

export function ChangeCard() {
  const id = useAdmin((s) => s.openChangeId);
  const detail = useAdmin((s) => s.changeDetail);
  const loading = useAdmin((s) => s.changeLoading);
  const error = useAdmin((s) => s.changeError);
  const saving = useAdmin((s) => s.changeSaving);
  const close = useAdmin((s) => s.closeChange);
  const act = useAdmin((s) => s.changeAction);
  const forbid = useAdmin((s) => s.forbidSimilar);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEscape(id !== null, close);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => before?.focus?.();
  }, []);

  if (!id) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-start sm:p-6" role="presentation">
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-title"
        className="card relative flex max-h-full w-full flex-col overflow-hidden rounded-none sm:max-h-[calc(100vh-3rem)] sm:max-w-3xl sm:rounded-2xl"
      >
        <header className="flex items-start gap-3 border-b border-line/70 p-4">
          <h2 id="change-title" className="min-w-0 flex-1 break-words font-display text-lg font-semibold">
            {detail ? `${detail.object_kind}: ${detail.object_key}` : "Change"}
          </h2>
          <button ref={closeRef} type="button" onClick={close} aria-label="Close" className={BTN_SM}>
            ✕
          </button>
        </header>
        <div className="overflow-y-auto p-4">
          {error && (
            <p role="alert" className="mb-3 rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
              {error}
            </p>
          )}
          {loading && <p className="text-sm text-muted">Loading…</p>}
          {detail && (
            <ChangeDetailView
              c={detail}
              saving={saving}
              onRevert={() => void act(id, "revert")}
              onReject={() => void act(id, "reject")}
              onForbid={(d) => void forbid(id, d)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
