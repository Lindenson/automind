/** Spec 010 T045 (FR-027): one issue — diagnosis, examples, "copy for Claude Code", status. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { fmtDate, fmtNum, useEscape } from "../lib/util";
import { FixBadge, STATUS_LABEL, StatusBadge, frequency } from "./badges";
import { CopyButton } from "./CopyButton";
import type { Diagnosis, Fix, ProblemDetail, StatusPatch } from "./schemas";
import { useAdmin } from "./store";

const BTN =
  "rounded-md border border-line px-3 py-1.5 text-sm font-medium hover:bg-panel2 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";

/** A configuration value as text (strings as they are, anything else as JSON). */
export function valueText(v: unknown): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

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

const PRE = "whitespace-pre-wrap break-words rounded-lg bg-panel2 p-2 font-mono text-xs";

export function FixDetails({ fix }: { fix: Fix }) {
  return (
    <dl className="space-y-2">
      <Field label="Proposed fix">
        <FixBadge fix={fix} />
      </Field>
      {fix.kind === "config" ? (
        <>
          <Field label="File">
            <code className="font-mono">{fix.config_file ?? "—"}</code>
          </Field>
          <Field label="Key">
            <code className="font-mono">{fix.config_key ?? "—"}</code>
          </Field>
          <Field label="Suggested value">
            <pre className={PRE}>{valueText(fix.suggested_value) || "—"}</pre>
          </Field>
        </>
      ) : (
        <>
          {fix.files.length > 0 && (
            <Field label="Files">
              <ul className="space-y-0.5">
                {fix.files.map((f) => (
                  <li key={f}>
                    <code className="font-mono">{f}</code>
                  </li>
                ))}
              </ul>
            </Field>
          )}
          {fix.direction && <Field label="Direction">{fix.direction}</Field>}
        </>
      )}
    </dl>
  );
}

export function DiagnosisView({ d }: { d: Diagnosis | null }) {
  if (!d) return <p className="text-sm text-muted">Not diagnosed yet.</p>;
  return (
    <div className="space-y-3">
      <dl className="space-y-2">
        {d.summary && <Field label="Summary">{d.summary}</Field>}
        {d.likely_cause && <Field label="Likely cause">{d.likely_cause}</Field>}
      </dl>
      {d.fix ? <FixDetails fix={d.fix} /> : <FixBadge fix={null} />}
    </div>
  );
}

export function StatusActions({
  status,
  saving,
  onStatus,
}: {
  status: string;
  saving: boolean;
  onStatus: (patch: StatusPatch) => void;
}) {
  const [ref, setRef] = useState("");
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={BTN}
          disabled={saving || status === "acknowledged"}
          onClick={() => onStatus({ status: "acknowledged" })}
        >
          Acknowledged
        </button>
        <button
          type="button"
          className={BTN}
          disabled={saving || status === "wontfix"}
          onClick={() => onStatus({ status: "wontfix" })}
        >
          Won't fix
        </button>
        <button
          type="button"
          className={BTN}
          disabled={saving || status === "open"}
          onClick={() => onStatus({ status: "open" })}
        >
          Reopen
        </button>
      </div>
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const r = ref.trim();
          onStatus(r ? { status: "fixed", fixed_ref: r } : { status: "fixed" });
        }}
      >
        <label className="sr-only" htmlFor="fixed-ref">
          Commit reference
        </label>
        <input
          id="fixed-ref"
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder="commit or PR (e.g. abc123)"
          className="min-w-0 flex-1 rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-sm placeholder:text-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        />
        <button type="submit" className={BTN} disabled={saving}>
          Fixed
        </button>
      </form>
    </div>
  );
}

/** The card's content without the dialog frame or the store (renders statically in tests). */
export function ProblemDetailView({
  detail,
  saving = false,
  onStatus = () => undefined,
}: {
  detail: ProblemDetail;
  saving?: boolean;
  onStatus?: (patch: StatusPatch) => void;
}) {
  const d = detail;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <StatusBadge status={d.status} />
        {d.failing_turns_7d != null && d.chats_7d != null && (
          <span>{frequency(d.failing_turns_7d, d.chats_7d)}</span>
        )}
        {d.impact != null && <span>impact {fmtNum(d.impact, 1)}</span>}
        {d.count_total != null && <span>{d.count_total} in total</span>}
        {d.first_seen && <span>first {fmtDate(d.first_seen)}</span>}
        {d.last_seen && <span>last {fmtDate(d.last_seen)}</span>}
        {d.component && <span className="chip">{d.component}</span>}
        {d.fixed_ref && (
          <span>
            fixed in <code className="font-mono text-fg">{d.fixed_ref}</code>
          </span>
        )}
      </div>

      <Section title="Diagnosis">
        <DiagnosisView d={d.diagnosis} />
      </Section>

      {d.diagnosis?.verify && (
        <Section title="Verify">
          <pre className={PRE}>{d.diagnosis.verify}</pre>
        </Section>
      )}

      <Section title="Copy for Claude Code">
        {d.copy_text ? (
          <CopyButton text={d.copy_text} label="Copy for Claude Code" className="px-3 py-1.5 text-sm" />
        ) : (
          <p className="text-sm text-muted">No task text yet.</p>
        )}
      </Section>

      <Section title={`Examples (${d.examples.length})`}>
        {d.examples.length === 0 ? (
          <p className="text-sm text-muted">No examples.</p>
        ) : (
          <ul className="space-y-2">
            {d.examples.map((ex, i) => (
              <li key={i} className="space-y-1 rounded-lg border border-line/70 p-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                  {ex.chat_id && (
                    <span className="inline-flex items-center gap-1">
                      chat <code className="font-mono text-fg">{ex.chat_id}</code>
                      <CopyButton
                        text={ex.chat_id}
                        label="copy"
                        copiedLabel="✓"
                        ariaLabel={`Copy chat id ${ex.chat_id}`}
                        className="px-1.5 py-0 text-[11px]"
                      />
                    </span>
                  )}
                  {ex.turn_id != null && <span>turn {String(ex.turn_id)}</span>}
                  {ex.claim_id != null && <span>claim {String(ex.claim_id)}</span>}
                  {ex.url && (
                    <a
                      href={ex.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="max-w-full truncate text-accent2 hover:underline"
                    >
                      {ex.url}
                    </a>
                  )}
                </div>
                {ex.quote && <pre className={PRE}>{ex.quote}</pre>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Status">
        <StatusActions status={d.status} saving={saving} onStatus={onStatus} />
      </Section>

      {d.history.length > 0 && (
        <Section title="Status history">
          <ol className="space-y-1 text-sm">
            {d.history.map((h, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                {h.at && <span className="text-xs text-muted">{fmtDate(h.at)}</span>}
                <span>{STATUS_LABEL[h.status] ?? h.status}</span>
                {(h.by ?? h.author) && <span className="text-xs text-muted">by {h.by ?? h.author}</span>}
                {h.fixed_ref && <code className="font-mono text-xs">{h.fixed_ref}</code>}
                {h.note && <span className="text-xs text-muted">{h.note}</span>}
              </li>
            ))}
          </ol>
        </Section>
      )}
    </div>
  );
}

/** The dialog: opens over the list, Escape or the backdrop closes it, focus returns to where it was. */
export function ProblemCard() {
  const openId = useAdmin((s) => s.openId);
  const detail = useAdmin((s) => s.detail);
  const loading = useAdmin((s) => s.detailLoading);
  const error = useAdmin((s) => s.detailError);
  const saving = useAdmin((s) => s.saving);
  const close = useAdmin((s) => s.closeProblem);
  const setStatus = useAdmin((s) => s.setStatus);
  const title = useAdmin((s) => s.problems?.find((p) => p.id === s.openId)?.title);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEscape(openId !== null, close);
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

  if (!openId) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center sm:items-start sm:p-6" role="presentation">
      <div className="absolute inset-0 bg-black/50" onClick={close} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="problem-title"
        className="card relative flex max-h-full w-full flex-col overflow-hidden rounded-none sm:max-h-[calc(100vh-3rem)] sm:max-w-2xl sm:rounded-2xl"
      >
        <header className="flex items-start gap-3 border-b border-line/70 p-4">
          <h2 id="problem-title" className="min-w-0 flex-1 font-display text-lg font-semibold">
            {detail?.title ?? title ?? "Problem"}
          </h2>
          <button ref={closeRef} type="button" onClick={close} aria-label="Close" className={BTN}>
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
            <ProblemDetailView detail={detail} saving={saving} onStatus={(patch) => void setStatus(detail.id, patch)} />
          )}
        </div>
      </div>
    </div>
  );
}
