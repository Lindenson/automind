/** Spec 011 T119 (US6, FR-021, SC-010): the accuracy drill-down — the KPI against the baseline and the components to
 * blame (click 1: a component) → its wrong values (click 2: a value) → the value with its source, producer, signals
 * and the page text around the quote, highlighted (click 3 is the tab itself). */
import { useEffect } from "react";
import { cx, fmtNum } from "../lib/util";
import type { Accuracy as AccuracyData, ValueDetail, WrongValue } from "./schemas";
import { BTN_SM, pct, when } from "./Sources";
import { useAdmin } from "./store";

const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";
const LINK =
  "text-left font-medium text-accent2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";

const share = (v: number | null): string => (v == null ? "—" : `${fmtNum(v * 100, 1)}%`);
const val = (v: string | number | boolean | null, unit?: string | null): string =>
  v == null ? "—" : `${typeof v === "number" ? fmtNum(v, 3) : String(v)}${unit ? ` ${unit}` : ""}`;

function Tile({ label, value, sub, bad }: { label: string; value: string; sub?: string; bad?: boolean }) {
  return (
    <div className="rounded-lg border border-line/70 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className={cx("font-display text-2xl font-semibold tabular-nums", bad && "text-bad")}>{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function KpiView({ a }: { a: AccuracyData }) {
  const k = a.kpi;
  const worse = k.wrong_share != null && k.baseline != null && k.wrong_share > k.baseline;
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      <Tile
        label="Wrong share (30 days)"
        value={share(k.wrong_share)}
        sub={`${k.wrong} wrong of ${k.accepted} accepted`}
        bad={worse}
      />
      <Tile
        label="Baseline"
        value={share(k.baseline)}
        sub={k.baseline_name ? `"${k.baseline_name}"` : "no closed baseline"}
      />
      <Tile label="Wrong against gold" value={share(k.gold_wrong_share)} sub="gold-checked values" />
    </div>
  );
}

export function AreaTable({ a }: { a: AccuracyData }) {
  if (a.by_area.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-line/70">
      <table className="w-full text-sm" aria-label="By kind of data">
        <thead className="bg-panel2/60">
          <tr>
            {["Kind of data", "Accepted", "Wrong", "Wrong share", "Baseline", "Gold checked", "Gold wrong"].map((h) => (
              <th key={h} scope="col" className={TH}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {a.by_area.map((r) => (
            <tr key={r.area} className="border-t border-line/60">
              <td className={TD}>{r.area.replace(/_/g, " ")}</td>
              <td className={cx(TD, "tabular-nums")}>{r.accepted}</td>
              <td className={cx(TD, "tabular-nums")}>{r.wrong}</td>
              <td className={cx(TD, "tabular-nums", r.baseline != null && (r.wrong_share ?? 0) > r.baseline && "text-bad")}>
                {share(r.wrong_share)}
              </td>
              <td className={cx(TD, "tabular-nums text-muted")}>{share(r.baseline)}</td>
              <td className={cx(TD, "tabular-nums")}>{r.gold_checked}</td>
              <td className={cx(TD, "tabular-nums")}>{share(r.gold_wrong_share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Click 1: the components ranked by wrong values. */
export function ComponentList({ a, onOpen }: { a: AccuracyData; onOpen: (component: string) => void }) {
  if (a.by_component.length === 0) return <p className="text-sm text-muted">No wrong values in 30 days.</p>;
  return (
    <ol className="space-y-1" aria-label="Components to blame">
      {a.by_component.map((c) => (
        <li key={c.component} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg border border-line/70 px-2.5 py-1.5">
          <button type="button" className={cx(LINK, "font-mono text-xs")} onClick={() => onOpen(c.component)}>
            {c.component}
          </button>
          <span className="text-sm">
            <strong className="text-bad">{c.wrong}</strong> wrong
            <span className="text-muted"> / {c.right} right</span>
          </span>
          {c.acc_lb != null && <span className="text-xs text-muted">accuracy LB {pct(c.acc_lb)}</span>}
        </li>
      ))}
    </ol>
  );
}

/** Click 2: the wrong values of one component. */
export function ValueList({ values, onOpen }: { values: WrongValue[]; onOpen: (claimId: string) => void }) {
  if (values.length === 0) return <p className="text-sm text-muted">No wrong values.</p>;
  return (
    <ol className="space-y-1" aria-label="Wrong values">
      {values.map((v) => (
        <li key={v.signal_id} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 rounded-lg border border-line/70 px-2.5 py-1.5 text-sm">
          {v.claim_id ? (
            <button type="button" className={LINK} onClick={() => onOpen(v.claim_id!)}>
              {v.variant ?? "variant"} · {v.attribute}
            </button>
          ) : (
            <span>
              {v.variant ?? "variant"} · {v.attribute}
            </span>
          )}
          <span>
            ours <strong className="text-bad">{val(v.ours, v.unit)}</strong>, truth{" "}
            <strong className="text-good">{val(v.truth, v.unit)}</strong>
          </span>
          <span className="text-xs text-muted">{v.truth_origin}</span>
          <span className="text-xs text-muted">{when(v.created_at)}</span>
        </li>
      ))}
    </ol>
  );
}

/** Where the quote is in the page text (case-insensitive, whitespace-tolerant). */
export function locate(text: string, quote: string): [number, number] | null {
  const q = quote.trim();
  if (!q) return null;
  const low = text.toLowerCase();
  for (const n of [q, q.split(/\s+/).join(" ")]) {
    const i = low.indexOf(n.toLowerCase());
    if (i >= 0) return [i, i + n.length];
  }
  return null;
}

export function PageText({ text, quote }: { text: string; quote: string }) {
  const at = locate(text, quote);
  return (
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-panel2 p-3 font-mono text-xs" aria-label="Page text">
      {at ? (
        <>
          {text.slice(0, at[0])}
          <mark className="rounded bg-warn/30 px-0.5 text-fg">{text.slice(at[0], at[1])}</mark>
          {text.slice(at[1])}
        </>
      ) : (
        text
      )}
    </pre>
  );
}

/** Click 3: the value — source, producer, model, signals and the page around the quote. */
export function ValuePanel({ v, pageText }: { v: ValueDetail; pageText: string | null }) {
  return (
    <div className="space-y-4">
      <dl className="grid gap-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="inline text-muted">Value: </dt>
          <dd className="inline">
            {v.claim.variant} · {v.claim.attribute} = <strong>{v.claim.raw_value}</strong> {v.claim.raw_unit ?? ""}
          </dd>
        </div>
        <div>
          <dt className="inline text-muted">Source: </dt>
          <dd className="inline break-all">
            {v.evidence.url ? (
              <a href={v.evidence.url} target="_blank" rel="noreferrer noopener" className="text-accent2 hover:underline">
                {v.evidence.domain ?? v.evidence.url}
              </a>
            ) : (
              v.evidence.domain
            )}{" "}
            <span className="text-muted">{v.evidence.source_type}</span>
          </dd>
        </div>
        <div>
          <dt className="inline text-muted">Producer: </dt>
          <dd className="inline font-mono text-xs">
            {v.producer} {v.producer_version}
            {v.model && ` · ${v.model}`}
          </dd>
        </div>
        <div>
          <dt className="inline text-muted">Page: </dt>
          <dd className="inline text-xs">{v.snapshot ? `snapshot of ${when(v.snapshot.fetched_at)}` : "no stored page"}</dd>
        </div>
      </dl>
      <section className="space-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Quote</h3>
        <blockquote className="border-l-2 border-warn pl-2 text-sm">{v.quote || "—"}</blockquote>
      </section>
      <section className="space-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Page text around the quote</h3>
        {pageText ? <PageText text={pageText} quote={v.quote} /> : <p className="text-sm text-muted">The page is not stored.</p>}
      </section>
      <section className="space-y-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Signals ({v.signals.length})</h3>
        <ul className="space-y-0.5 text-sm">
          {v.signals.map((s, i) => (
            <li key={s.id ?? i} className="flex flex-wrap gap-x-2">
              <span className="text-xs text-muted">{when(s.at)}</span>
              <span className="chip text-[11px]">{s.kind}</span>
              <span className={s.verdict === "wrong" ? "text-bad" : "text-good"}>{s.verdict}</span>
              {s.component && <code className="font-mono text-xs">{s.component}</code>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export interface DrillState {
  accuracy: AccuracyData | null;
  component: string | null;
  wrongValues: WrongValue[] | null;
  claimId: string | null;
  valueDetail: ValueDetail | null;
  pageText: string | null;
}

export function DrillView({
  s,
  onComponent,
  onValue,
  onBack,
  onTop,
}: {
  s: DrillState;
  onComponent: (c: string) => void;
  onValue: (id: string) => void;
  onBack: () => void;
  onTop: () => void;
}) {
  const crumbs = (
    <nav aria-label="Drill-down" className="flex flex-wrap items-center gap-1 text-sm">
      <button type="button" className={LINK} onClick={onTop}>
        Accuracy
      </button>
      {s.component && (
        <>
          <span className="text-muted">›</span>
          {s.claimId ? (
            <button type="button" className={cx(LINK, "font-mono text-xs")} onClick={onBack}>
              {s.component}
            </button>
          ) : (
            <span className="font-mono text-xs">{s.component}</span>
          )}
        </>
      )}
      {s.claimId && (
        <>
          <span className="text-muted">›</span>
          <span>{s.valueDetail ? `${s.valueDetail.claim.attribute}` : "value"}</span>
        </>
      )}
    </nav>
  );
  if (s.claimId) {
    return (
      <div className="space-y-3">
        {crumbs}
        {s.valueDetail && <ValuePanel v={s.valueDetail} pageText={s.pageText} />}
      </div>
    );
  }
  if (s.component) {
    return (
      <div className="space-y-3">
        {crumbs}
        {s.wrongValues && <ValueList values={s.wrongValues} onOpen={onValue} />}
      </div>
    );
  }
  if (!s.accuracy) return null;
  return (
    <div className="space-y-4">
      <KpiView a={s.accuracy} />
      <AreaTable a={s.accuracy} />
      <section className="space-y-2">
        <h2 className="font-display text-base font-semibold">Components to blame</h2>
        <ComponentList a={s.accuracy} onOpen={onComponent} />
      </section>
    </div>
  );
}

export function Accuracy() {
  const accuracy = useAdmin((s) => s.accuracy);
  const loading = useAdmin((s) => s.accuracyLoading);
  const error = useAdmin((s) => s.accuracyError);
  const component = useAdmin((s) => s.component);
  const wrongValues = useAdmin((s) => s.wrongValues);
  const claimId = useAdmin((s) => s.claimId);
  const valueDetail = useAdmin((s) => s.valueDetail);
  const pageText = useAdmin((s) => s.pageText);
  const drillLoading = useAdmin((s) => s.drillLoading);
  const drillError = useAdmin((s) => s.drillError);
  const load = useAdmin((s) => s.loadAccuracy);
  const openComponent = useAdmin((s) => s.openComponent);
  const openValue = useAdmin((s) => s.openValue);
  const back = useAdmin((s) => s.drillBack);

  useEffect(() => {
    if (useAdmin.getState().accuracy === null) void load();
  }, [load]);

  const top = () => useAdmin.setState({ component: null, wrongValues: null, claimId: null, valueDetail: null, pageText: null });

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted">From the accuracy KPI to the component, the value, the page and the quote.</p>
        <button type="button" onClick={() => void load()} disabled={loading} className={BTN_SM}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {(error || drillError) && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error ?? drillError}
        </p>
      )}
      <DrillView
        s={{ accuracy, component, wrongValues, claimId, valueDetail, pageText }}
        onComponent={(c) => void openComponent(c)}
        onValue={(id) => void openValue(id)}
        onBack={back}
        onTop={top}
      />
      {(loading || drillLoading) && <p className="text-sm text-muted">Loading…</p>}
    </section>
  );
}
