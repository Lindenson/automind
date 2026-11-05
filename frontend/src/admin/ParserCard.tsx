/** Spec 011 T117 (US6): one parser — daily fields per page and pass rate per version with drift markers and version
 * switches, versions, drift signals, the spec of each version; Roll back to a chosen version, Freeze / Unfreeze. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cx, useEscape } from "../lib/util";
import type { ParserAction } from "./api";
import { SourceStatusBadge } from "./badges";
import { LineChart, type Marker, type Series } from "./charts";
import { fpp } from "./Parsers";
import type { ParserDetail } from "./schemas";
import { BTN_SM, pct, when } from "./Sources";
import { useAdmin } from "./store";

const BTN =
  "rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-panel2 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";
const PRE = "max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-panel2 p-2 font-mono text-xs";
const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

/** Versions the owner may restore: once active, not the running one. */
export function rollbackTargets(d: ParserDetail): string[] {
  return d.versions
    .filter((v) => v.key !== d.active && v.activated_at && ["superseded", "degraded", "retired"].includes(v.status))
    .map((v) => v.key);
}

/** Days on the x axis, one series per version, drift and version-switch markers. */
export function chartData(d: ParserDetail, metric: "fields_per_page" | "pass_rate") {
  const days = [...new Set(d.daily.map((r) => r.day))].sort();
  const index = new Map(days.map((day, i) => [day, i]));
  const keys = [...new Set(d.daily.map((r) => r.version_key))].sort();
  const series: Series[] = keys.map((key) => {
    const values: (number | null)[] = days.map(() => null);
    for (const r of d.daily) if (r.version_key === key) values[index.get(r.day)!] = r[metric];
    return { label: key, values };
  });
  const markers: Marker[] = [];
  for (const s of d.drift_signals) {
    const at = s.day ? index.get(s.day) : undefined;
    if (at !== undefined) markers.push({ at, label: `drift ${s.kind} (${s.version ?? ""})`, tone: "bad" });
  }
  for (const v of d.versions) {
    const at = v.activated_at ? index.get(v.activated_at.slice(0, 10)) : undefined;
    if (at !== undefined) markers.push({ at, label: `${v.key} activated`, tone: "accent" });
  }
  return { days, series, markers };
}

export function ParserActions({
  detail,
  saving,
  onAction,
  onRollback,
}: {
  detail: ParserDetail;
  saving: boolean;
  onAction?: (a: ParserAction) => void;
  onRollback?: (to: string) => void;
}) {
  const targets = rollbackTargets(detail);
  const first = targets[0] ?? "";
  const [to, setTo] = useState(first);
  useEffect(() => setTo(first), [first]);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={BTN}
          disabled={saving}
          onClick={() => onAction?.(detail.frozen ? "unfreeze" : "freeze")}
        >
          {detail.frozen ? "Unfreeze" : "Freeze"}
        </button>
        <label className="sr-only" htmlFor="rollback-to">
          Version to restore
        </label>
        <select
          id="rollback-to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          disabled={saving || targets.length === 0}
          className="rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        >
          {targets.length === 0 && <option value="">no previous version</option>}
          {targets.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={cx(BTN, "border-warn/50 text-warn")}
          disabled={saving || !to}
          onClick={() => to && onRollback?.(to)}
        >
          Roll back
        </button>
      </div>
      <p className="text-xs text-muted">
        Frozen: no agent may propose a change to this parser. Roll back: the chosen version runs again and the change
        that installed the current one is marked reverted.
      </p>
    </div>
  );
}

export function ParserDetailView({
  detail,
  saving = false,
  onAction,
  onRollback,
}: {
  detail: ParserDetail;
  saving?: boolean;
  onAction?: (a: ParserAction) => void;
  onRollback?: (to: string) => void;
}) {
  const yieldChart = chartData(detail, "fields_per_page");
  const passChart = chartData(detail, "pass_rate");
  return (
    <div className="space-y-5">
      <dl className="grid gap-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="inline text-muted">Domains: </dt>
          <dd className="inline">{detail.domains.join(", ") || "—"}</dd>
        </div>
        <div>
          <dt className="inline text-muted">Active: </dt>
          <dd className="inline font-mono text-xs">{detail.active ?? "—"}</dd>
          {detail.frozen && <span className="chip ml-2 text-[11px]">❄ frozen</span>}
        </div>
        {detail.canary && (
          <div>
            <dt className="inline text-muted">Canary: </dt>
            <dd className="inline">
              {detail.canary.phase}
              {detail.canary.day != null && detail.canary.of != null && ` day ${detail.canary.day} of ${detail.canary.of}`}
              {detail.canary.ends_at && `, ends ${when(detail.canary.ends_at)}`}
            </dd>
          </div>
        )}
      </dl>

      <ParserActions detail={detail} saving={saving} onAction={onAction} onRollback={onRollback} />

      <Section title="Fields per page by day (60 days)">
        <LineChart label="Fields per page by version" format={fpp} {...yieldChart} />
      </Section>
      <Section title="Pass rate by day">
        <LineChart label="Pass rate by version" format={pct} {...passChart} />
      </Section>

      <Section title={`Versions (${detail.versions.length})`}>
        <div className="overflow-x-auto rounded-lg border border-line/70">
          <table className="w-full text-sm" aria-label="Versions">
            <thead className="bg-panel2/60">
              <tr>
                <th scope="col" className={TH}>
                  Version
                </th>
                <th scope="col" className={TH}>
                  Status
                </th>
                <th scope="col" className={TH}>
                  Author
                </th>
                <th scope="col" className={TH}>
                  Activated
                </th>
                <th scope="col" className={TH}>
                  Note
                </th>
              </tr>
            </thead>
            <tbody>
              {detail.versions.map((v) => (
                <tr key={v.key} className="border-t border-line/60">
                  <td className={cx(TD, "font-mono text-xs")}>{v.key}</td>
                  <td className={TD}>
                    <SourceStatusBadge status={v.status} />
                  </td>
                  <td className={cx(TD, "text-xs")}>{v.author ?? "—"}</td>
                  <td className={cx(TD, "text-xs")}>{when(v.activated_at)}</td>
                  <td className="px-2 py-1.5 text-xs text-muted">{v.degraded_reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title={`Drift signals (${detail.drift_signals.length})`}>
        {detail.drift_signals.length === 0 ? (
          <p className="text-sm text-muted">No drift in 60 days.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {detail.drift_signals.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-2">
                <span className="text-xs text-muted">{s.day}</span>
                <span className="chip text-[11px] text-bad">{s.kind.replace(/_/g, " ")}</span>
                <span className="font-mono text-xs">{s.version}</span>
                <span className="min-w-0 break-words">{s.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Specs">
        {Object.entries(detail.specs).map(([key, spec]) => (
          <details key={key} className="rounded-lg border border-line/70 p-2">
            <summary className="cursor-pointer font-mono text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2">
              {key}
            </summary>
            <pre className={cx(PRE, "mt-2")}>{JSON.stringify(spec, null, 2)}</pre>
          </details>
        ))}
      </Section>
    </div>
  );
}

/** The dialog over the parser list (Escape or the backdrop closes it). */
export function ParserCard() {
  const reader = useAdmin((s) => s.openReader);
  const detail = useAdmin((s) => s.parserDetail);
  const loading = useAdmin((s) => s.parserLoading);
  const error = useAdmin((s) => s.parserError);
  const saving = useAdmin((s) => s.parserSaving);
  const close = useAdmin((s) => s.closeParser);
  const act = useAdmin((s) => s.parserAction);
  const rollback = useAdmin((s) => s.rollbackParser);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEscape(reader !== null, close);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => before?.focus?.();
  }, []);

  if (!reader) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-start sm:p-6" role="presentation">
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="parser-title"
        className="card relative flex max-h-full w-full flex-col overflow-hidden rounded-none sm:max-h-[calc(100vh-3rem)] sm:max-w-3xl sm:rounded-2xl"
      >
        <header className="flex items-start gap-3 border-b border-line/70 p-4">
          <h2 id="parser-title" className="min-w-0 flex-1 break-words font-display text-lg font-semibold">
            Parser {reader}
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
            <ParserDetailView
              detail={detail}
              saving={saving}
              onAction={(a) => void act(reader, a)}
              onRollback={(to) => void rollback(reader, to)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
