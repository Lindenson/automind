/** Spec 010 T069 (US7, FR-028): one source — access evidence, capabilities, history, last signals; freeze / block. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cx, fmtNum, useEscape } from "../lib/util";
import type { SourceAction } from "./api";
import { SourceStatusBadge } from "./badges";
import { valueText } from "./ProblemCard";
import type { SourceDetail } from "./schemas";
import { BTN_SM, ChangeList, Marks, eur, pct, when } from "./Sources";
import { useAdmin } from "./store";

const BTN =
  "rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-panel2 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";
const PRE = "whitespace-pre-wrap break-words rounded-lg bg-panel2 p-2 font-mono text-xs";
const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[8rem_1fr] sm:gap-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-sm">{children}</dd>
    </div>
  );
}

/** Freeze / unfreeze at once; block only after a confirm step. */
export function SourceActions({
  domain,
  frozen,
  blocked,
  saving,
  onAction,
}: {
  domain: string;
  frozen: boolean;
  blocked: boolean;
  saving: boolean;
  onAction: (action: SourceAction) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (confirm) confirmRef.current?.focus();
  }, [confirm]);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={BTN}
          disabled={saving}
          onClick={() => onAction(frozen ? "unfreeze" : "freeze")}
        >
          {frozen ? "Unfreeze" : "Freeze"}
        </button>
        {!confirm && (
          <button
            type="button"
            className={cx(BTN, "border-bad/50 text-bad")}
            disabled={saving || blocked}
            onClick={() => setConfirm(true)}
          >
            Block…
          </button>
        )}
      </div>
      <p className="text-xs text-muted">
        Frozen: the system may not change this source. Blocked: it is never used; a revert in the history undoes it.
      </p>
      {confirm && (
        <div role="group" aria-label="Confirm block" className="space-y-2 rounded-lg border border-bad/40 bg-bad/10 p-3">
          <p className="text-sm">
            Block <strong>{domain}</strong> for every kind of data? It will not be used.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              ref={confirmRef}
              type="button"
              className={cx(BTN, "border-bad/60 bg-bad/15 text-bad")}
              disabled={saving}
              onClick={() => {
                setConfirm(false);
                onAction("block");
              }}
            >
              Block {domain}
            </button>
            <button type="button" className={BTN} onClick={() => setConfirm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** The card's content without the dialog frame or the store (renders statically in tests). */
export function SourceDetailView({
  detail,
  saving = false,
  revertErrors = {},
  reverting = null,
  onAction = () => undefined,
  onRevert,
}: {
  detail: SourceDetail;
  saving?: boolean;
  revertErrors?: Record<string, string>;
  reverting?: string | null;
  onAction?: (action: SourceAction) => void;
  onRevert?: (id: string) => void;
}) {
  const s = detail.source;
  const evidence = Object.entries(s.access_evidence).filter(([, v]) => v !== null && v !== undefined && v !== "");
  const caps = detail.capabilities;
  const blocked = caps.length > 0 && caps.every((c) => c.status === "blocked");
  return (
    <div className="space-y-5">
      <Section title="Source">
        <dl className="space-y-2">
          <Field label="Type">{s.source_type ?? "—"}</Field>
          {s.family && <Field label="Family">{s.family}</Field>}
          {s.markets.length > 0 && <Field label="Markets">{s.markets.join(", ")}</Field>}
          {s.languages.length > 0 && <Field label="Languages">{s.languages.join(", ")}</Field>}
          <Field label="Access">
            <code className="font-mono">{s.access}</code>
          </Field>
          <Field label="Checked">{when(s.checked_at)}</Field>
          <Field label="Next check">{when(s.next_check_at)}</Field>
          <Field label="Frozen">{s.frozen ? "yes — the system may not change it" : "no"}</Field>
          {s.note && <Field label="Note">{s.note}</Field>}
        </dl>
      </Section>

      <Section title="Access evidence">
        {evidence.length === 0 ? (
          <p className="text-sm text-muted">No evidence recorded.</p>
        ) : (
          <dl className="space-y-2">
            {evidence.map(([k, v]) => (
              <Field key={k} label={k.replace(/_/g, " ")}>
                <pre className={PRE}>{valueText(v)}</pre>
              </Field>
            ))}
          </dl>
        )}
      </Section>

      <Section title="Actions">
        <SourceActions domain={s.domain} frozen={s.frozen} blocked={blocked} saving={saving} onAction={onAction} />
      </Section>

      <Section title={`Capabilities (${caps.length})`}>
        {caps.length === 0 ? (
          <p className="text-sm text-muted">No capabilities.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line/70">
            <table className="w-full text-sm" aria-label="Capabilities">
              <thead className="bg-panel2/60">
                <tr>
                  {["Kind", "Market", "Status", "Score", "Acc LB", "Acc mean", "Yield", "Attempts", "€ / value"].map((h) => (
                    <th key={h} scope="col" className={TH}>
                      {h}
                    </th>
                  ))}
                  <th scope="col" className={TH}>
                    <span className="sr-only">Marks</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {caps.map((c) => (
                  <tr key={c.capability_id} className="border-t border-line/60">
                    <td className={TD}>{typeof c.area === "string" ? c.area : "—"}</td>
                    <td className={TD}>{c.market || "—"}</td>
                    <td className={TD}>
                      <SourceStatusBadge status={c.status} />
                    </td>
                    <td className={cx(TD, "tabular-nums")}>{fmtNum(c.score, 3)}</td>
                    <td className={cx(TD, "tabular-nums")}>{pct(c.acc_lb)}</td>
                    <td className={cx(TD, "tabular-nums")}>{pct(c.acc_mean)}</td>
                    <td className={cx(TD, "tabular-nums")}>{pct(c.yield)}</td>
                    <td className={cx(TD, "tabular-nums")}>{fmtNum(c.attempts, 1)}</td>
                    <td className={cx(TD, "tabular-nums")}>{eur(c.cost_per_value)}</td>
                    <td className={TD}>
                      <Marks c={c} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title={`History (${detail.changes.length})`}>
        <ChangeList
          changes={detail.changes}
          errors={revertErrors}
          reverting={reverting}
          onRevert={onRevert}
          label="History"
        />
      </Section>

      <Section title={`Last signals (${detail.signals.length})`}>
        {detail.signals.length === 0 ? (
          <p className="text-sm text-muted">No signals.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {detail.signals.map((x, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="text-xs text-muted">{when(x.at)}</span>
                <span className="chip text-[11px]">{x.kind}</span>
                {x.verdict && <span className="font-medium">{x.verdict}</span>}
                {x.blame && <span className="text-xs text-muted">blame: {x.blame}</span>}
                {x.attribute && <code className="font-mono text-xs">{x.attribute}</code>}
                {x.weight != null && <span className="text-xs text-muted">w {fmtNum(x.weight, 2)}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

/** The dialog: opens over the list, Escape or the backdrop closes it, focus returns to where it was. */
export function SourceCard() {
  const domain = useAdmin((s) => s.openDomain);
  const detail = useAdmin((s) => s.sourceDetail);
  const loading = useAdmin((s) => s.sourceLoading);
  const error = useAdmin((s) => s.sourceError);
  const saving = useAdmin((s) => s.sourceSaving);
  const revertErrors = useAdmin((s) => s.revertErrors);
  const reverting = useAdmin((s) => s.reverting);
  const close = useAdmin((s) => s.closeSource);
  const act = useAdmin((s) => s.sourceAction);
  const revert = useAdmin((s) => s.revertChange);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEscape(domain !== null, close);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
      before?.focus?.();
    };
  }, []);

  if (!domain) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-start sm:p-6" role="presentation">
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-title"
        className="card relative flex max-h-full w-full flex-col overflow-hidden rounded-none sm:max-h-[calc(100vh-3rem)] sm:max-w-3xl sm:rounded-2xl"
      >
        <header className="flex items-start gap-3 border-b border-line/70 p-4">
          <h2 id="source-title" className="min-w-0 flex-1 break-words font-display text-lg font-semibold">
            {domain}
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
            <SourceDetailView
              detail={detail}
              saving={saving}
              revertErrors={revertErrors}
              reverting={reverting}
              onAction={(a) => void act(domain, a)}
              onRevert={(id) => void revert(id)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
