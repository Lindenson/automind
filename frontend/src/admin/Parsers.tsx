/** Spec 011 T117 (US6, FR-021): the Parsers screen — one line per site reader: active version and status, 7 days vs
 * the 30 days before (fields per page, pass rate), drift, a running canary; the card opens on the reader. */
import { useEffect } from "react";
import { cx, fmtNum } from "../lib/util";
import { SourceStatusBadge } from "./badges";
import { Sparkline } from "./charts";
import { ParserCard } from "./ParserCard";
import type { ParserItem, WindowStats } from "./schemas";
import { BTN_SM, pct } from "./Sources";
import { useAdmin } from "./store";

const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

/** "11.0 / 11.3" with the 7-day value red when it fell more than 20 % below the 30 days before. */
export function VsCell({
  now,
  before,
  fmt,
  label,
}: {
  now: number | null;
  before: number | null;
  fmt: (v: number) => string;
  label: string;
}) {
  const drop = now != null && before != null && before > 0 && now < before * 0.8;
  return (
    <span aria-label={`${label}: ${now == null ? "no data" : fmt(now)} in 7 days, ${before == null ? "no data" : fmt(before)} in the 30 days before`}>
      <span className={cx("tabular-nums", drop && "font-semibold text-bad")}>{now == null ? "—" : fmt(now)}</span>
      <span className="text-muted"> / {before == null ? "—" : fmt(before)}</span>
    </span>
  );
}

export const fpp = (v: number): string => fmtNum(v, 1);

export function DriftBadge({ drift }: { drift: ParserItem["drift"] }) {
  if (!drift) return <span className="text-xs text-muted">—</span>;
  return (
    <span className="chip text-[11px] text-bad" title={drift.detail ?? undefined}>
      drift: {drift.kind.replace(/_/g, " ")}
    </span>
  );
}

export function CanaryBadge({ canary }: { canary: ParserItem["canary"] }) {
  if (!canary) return <span className="text-xs text-muted">—</span>;
  const progress = canary.day != null && canary.of != null ? ` ${canary.day}/${canary.of}` : "";
  return (
    <span className="chip text-[11px] text-accent2" title={`change ${canary.change_id}`}>
      {canary.phase}
      {progress}
    </span>
  );
}

export function ParserRow({ p, onOpen }: { p: ParserItem; onOpen: (reader: string) => void }) {
  const last: WindowStats = p.last_7d;
  const base: WindowStats = p.baseline_30d;
  return (
    <tr className="border-t border-line/60">
      <td className={TD}>
        <button
          type="button"
          onClick={() => onOpen(p.reader)}
          className="font-medium text-accent2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        >
          {p.reader}
        </button>
        {p.frozen && (
          <span className="chip ml-1 text-[11px]" title="Frozen by the owner: no agent may change it">
            ❄ frozen
          </span>
        )}
      </td>
      <td className={cx(TD, "font-mono text-xs")}>{p.active ?? "—"}</td>
      <td className={TD}>{p.active_status ? <SourceStatusBadge status={p.active_status} /> : "—"}</td>
      <td className={TD}>
        <VsCell now={last.fields_per_page} before={base.fields_per_page} fmt={fpp} label="fields per page" />
      </td>
      <td className={TD}>
        <VsCell now={last.pass_rate} before={base.pass_rate} fmt={pct} label="pass rate" />
      </td>
      <td className={TD}>
        {p.spark_30d.length > 1 ? (
          <Sparkline values={p.spark_30d.map((d) => d.fields_per_page)} label={`${p.reader}: fields per page, 30 days`} />
        ) : (
          <span className="text-xs text-muted">—</span>
        )}
      </td>
      <td className={cx(TD, "tabular-nums")}>{last.pages}</td>
      <td className={TD}>
        <DriftBadge drift={p.drift} />
      </td>
      <td className={TD}>
        <CanaryBadge canary={p.canary} />
      </td>
    </tr>
  );
}

export function ParserTable({ rows, onOpen }: { rows: ParserItem[]; onOpen: (reader: string) => void }) {
  if (rows.length === 0) return <p className="card p-4 text-center text-sm text-muted">No parsers yet.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-line/70">
      <table className="w-full text-sm" aria-label="Parsers">
        <thead className="bg-panel2/60">
          <tr>
            <th scope="col" className={TH}>
              Reader
            </th>
            <th scope="col" className={TH}>
              Active
            </th>
            <th scope="col" className={TH}>
              Status
            </th>
            <th scope="col" className={TH} title="Fields per page: last 7 days / the 30 days before">
              Fields/page 7d / 30d
            </th>
            <th scope="col" className={TH} title="Pass rate: last 7 days / the 30 days before">
              Pass 7d / 30d
            </th>
            <th scope="col" className={TH} title="Fields per page by day, last 30 days">
              Trend 30d
            </th>
            <th scope="col" className={TH}>
              Pages 7d
            </th>
            <th scope="col" className={TH}>
              Drift
            </th>
            <th scope="col" className={TH}>
              Canary
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <ParserRow key={p.reader} p={p} onOpen={onOpen} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Parsers() {
  const rows = useAdmin((s) => s.parsers);
  const loading = useAdmin((s) => s.parsersLoading);
  const error = useAdmin((s) => s.parsersError);
  const openReader = useAdmin((s) => s.openReader);
  const load = useAdmin((s) => s.loadParsers);
  const open = useAdmin((s) => s.openParser);

  useEffect(() => {
    if (useAdmin.getState().parsers === null) void load();
  }, [load]);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted">Site readers: versions, yield and pass rate, drift, canaries.</p>
        <button type="button" onClick={() => void load()} disabled={loading} className={BTN_SM}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </p>
      )}
      {rows ? <ParserTable rows={rows} onOpen={(r) => void open(r)} /> : loading && <p className="text-sm text-muted">Loading…</p>}
      {openReader && <ParserCard />}
    </section>
  );
}
