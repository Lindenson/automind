/** Spec 010 T069 (US7, FR-028): the Sources screen — the registry by kind of data, and its recent changes. */
import { useEffect, useId, useState } from "react";
import { cx, fmtDate, fmtNum, fmtTime } from "../lib/util";
import { ChangeBadge, SourceStatusBadge, accessMark } from "./badges";
import { SourceCard } from "./SourceCard";
import { AREAS, USABLE_STATUSES, type Capability, type Change, type SourceList } from "./schemas";
import { useAdmin } from "./store";

export const BTN_SM =
  "rounded-md border border-line px-2.5 py-1 text-xs font-medium hover:bg-panel2 disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2";

export const pct = (v: number): string => `${Math.round(v * 100)}%`;
export const eur = (v: number | null): string => (v == null ? "—" : `€${fmtNum(v, 4)}`);
export const when = (iso: string | null | undefined): string => (iso ? `${fmtDate(iso)} ${fmtTime(iso)}`.trim() : "—");

const STATUS_ORDER = ["active", "candidate", "degraded", "retired", "blocked"];

export function AutonomyBanner({ on }: { on: boolean }) {
  return on ? (
    <p role="status" className="rounded-lg border border-good/40 bg-good/10 p-3 text-sm">
      <strong>Autonomy on:</strong> the registry changes itself and research uses its order.
    </p>
  ) : (
    <p role="status" className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
      <strong>Autonomy off:</strong> the registry records and scores, the configured order is used.
    </p>
  );
}

export function StatusCounts({ counts }: { counts: Record<string, number> }) {
  const keys = [...STATUS_ORDER.filter((k) => k in counts), ...Object.keys(counts).filter((k) => !STATUS_ORDER.includes(k))];
  if (keys.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-2 text-xs" aria-label="Counts by status">
      {keys.map((k) => (
        <li key={k} className="inline-flex items-center gap-1">
          <SourceStatusBadge status={k} />
          <span className="font-semibold">{counts[k]}</span>
        </li>
      ))}
    </ul>
  );
}

/** The lower bound of accuracy; hover (title) or tap shows the mean too. */
export function AccCell({ lb, mean }: { lb: number; mean: number }) {
  const [show, setShow] = useState(false);
  return (
    <button
      type="button"
      title={`mean ${pct(mean)}`}
      aria-label={`accuracy lower bound ${pct(lb)}, mean ${pct(mean)}`}
      aria-pressed={show}
      onClick={() => setShow((v) => !v)}
      className="rounded px-1 tabular-nums underline decoration-dotted underline-offset-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
    >
      {pct(lb)}
      {show && <span className="text-muted"> / {pct(mean)}</span>}
    </button>
  );
}

export function Marks({ c }: { c: Capability }) {
  const access = accessMark(c.access);
  if (!c.frozen && !access) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {c.frozen && (
        <span className="chip text-[11px]" title="Frozen by the owner: the system may not change it">
          ❄ frozen
        </span>
      )}
      {access && (
        <span className="chip text-[11px] text-warn" title={`access: ${c.access}`}>
          {access}
        </span>
      )}
    </span>
  );
}

const TH = "px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-2 py-1.5 whitespace-nowrap";

function Row({ c, onOpen }: { c: Capability; onOpen: (domain: string) => void }) {
  return (
    <tr className="border-t border-line/60">
      <td className={cx(TD, "text-right text-muted tabular-nums")}>{c.rank ?? "—"}</td>
      <td className={TD}>
        <button
          type="button"
          onClick={() => onOpen(c.domain)}
          className="font-medium text-accent2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        >
          {c.domain}
        </button>
      </td>
      <td className={TD}>{c.market || "—"}</td>
      <td className={TD}>
        <SourceStatusBadge status={c.status} />
      </td>
      <td className={cx(TD, "tabular-nums")}>{fmtNum(c.score, 3)}</td>
      <td className={TD}>
        <AccCell lb={c.acc_lb} mean={c.acc_mean} />
      </td>
      <td className={cx(TD, "tabular-nums")}>{pct(c.yield)}</td>
      <td className={cx(TD, "tabular-nums")}>{fmtNum(c.attempts, 1)}</td>
      <td className={cx(TD, "tabular-nums")}>{eur(c.cost_per_value)}</td>
      <td className={TD}>
        <Marks c={c} />
      </td>
    </tr>
  );
}

function Table({ rows, label, onOpen }: { rows: Capability[]; label: string; onOpen: (domain: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line/70">
      <table className="w-full text-sm" aria-label={label}>
        <thead className="bg-panel2/60">
          <tr>
            <th scope="col" className={cx(TH, "text-right")}>
              #
            </th>
            <th scope="col" className={TH}>
              Domain
            </th>
            <th scope="col" className={TH}>
              Market
            </th>
            <th scope="col" className={TH}>
              Status
            </th>
            <th scope="col" className={TH}>
              Score
            </th>
            <th scope="col" className={TH} title="Accuracy lower bound (tap for the mean)">
              Acc LB
            </th>
            <th scope="col" className={TH}>
              Yield
            </th>
            <th scope="col" className={TH}>
              Attempts
            </th>
            <th scope="col" className={TH}>
              € / value
            </th>
            <th scope="col" className={TH}>
              <span className="sr-only">Marks</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <Row key={c.capability_id} c={c} onOpen={onOpen} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Usable capabilities in rank order; blocked and retired ones collapsed under "Not used (N)". */
export function SourceTable({ list, onOpen }: { list: SourceList; onOpen: (domain: string) => void }) {
  const used = list.sources.filter((c) => USABLE_STATUSES.includes(c.status));
  const unused = list.sources.filter((c) => !USABLE_STATUSES.includes(c.status));
  return (
    <div className="space-y-3">
      {used.length === 0 ? (
        <p className="card p-4 text-center text-sm text-muted">No usable sources for this kind of data.</p>
      ) : (
        <Table rows={used} label={`Sources of ${list.area}`} onOpen={onOpen} />
      )}
      {unused.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer rounded text-sm text-muted hover:text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2">
            Not used ({unused.length})
          </summary>
          <div className="mt-2">
            <Table rows={unused} label={`Not used sources of ${list.area}`} onOpen={onOpen} />
          </div>
        </details>
      )}
    </div>
  );
}

export function ChangeItem({
  c,
  error,
  reverting = false,
  onRevert,
  onOpen,
}: {
  c: Change;
  error?: string | undefined;
  reverting?: boolean;
  onRevert?: (id: string) => void;
  onOpen?: (domain: string) => void;
}) {
  const where = [c.area, c.market].filter(Boolean).join(" / ");
  return (
    <li className="space-y-1 rounded-lg border border-line/70 p-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <time className="text-muted" dateTime={c.at ?? undefined}>
          {when(c.at)}
        </time>
        <ChangeBadge c={c} />
        {onOpen ? (
          <button
            type="button"
            onClick={() => onOpen(c.domain)}
            className="font-medium text-accent2 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
          >
            {c.domain}
          </button>
        ) : (
          <span className="font-medium">{c.domain}</span>
        )}
        {where && <span className="text-muted">{where}</span>}
        {c.author && <span className="text-muted">by {c.author}</span>}
        {c.reverted && <span className="chip text-[11px]">reverted</span>}
        {c.revertible && onRevert && (
          <button
            type="button"
            className={cx(BTN_SM, "ml-auto")}
            disabled={reverting}
            onClick={() => onRevert(c.id)}
            aria-label={`Revert: ${c.change} ${c.domain}`}
          >
            {reverting ? "Reverting…" : "Revert"}
          </button>
        )}
      </div>
      {c.reason && <p className="break-words text-sm">{c.reason}</p>}
      {error && (
        <p role="alert" className="text-xs text-bad">
          {error}
        </p>
      )}
    </li>
  );
}

export function ChangeList({
  changes,
  errors = {},
  reverting = null,
  onRevert,
  onOpen,
  label = "Recent changes",
}: {
  changes: Change[];
  errors?: Record<string, string>;
  reverting?: string | null;
  onRevert?: (id: string) => void;
  onOpen?: (domain: string) => void;
  label?: string;
}) {
  if (changes.length === 0) return <p className="text-sm text-muted">No changes.</p>;
  return (
    <ol className="space-y-2" aria-label={label}>
      {changes.map((c) => (
        <ChangeItem
          key={c.id}
          c={c}
          error={errors[c.id]}
          reverting={reverting === c.id}
          onRevert={onRevert}
          onOpen={onOpen}
        />
      ))}
    </ol>
  );
}

export function Sources() {
  const area = useAdmin((s) => s.area);
  const list = useAdmin((s) => s.sources);
  const loading = useAdmin((s) => s.sourcesLoading);
  const error = useAdmin((s) => s.sourcesError);
  const changes = useAdmin((s) => s.changes);
  const changesError = useAdmin((s) => s.changesError);
  const revertErrors = useAdmin((s) => s.revertErrors);
  const reverting = useAdmin((s) => s.reverting);
  const openDomain = useAdmin((s) => s.openDomain);
  const load = useAdmin((s) => s.loadSources);
  const setArea = useAdmin((s) => s.setArea);
  const open = useAdmin((s) => s.openSource);
  const revert = useAdmin((s) => s.revertChange);
  const selectId = useId();

  useEffect(() => {
    if (useAdmin.getState().sources === null) void load();
  }, [load]);

  const onOpen = (d: string) => void open(d);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <label htmlFor={selectId} className="text-sm text-muted">
            Kind of data
          </label>
          <select
            id={selectId}
            value={area}
            onChange={(e) => void setArea(e.target.value)}
            className="rounded-md border border-line bg-panel2 px-2 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
          >
            {AREAS.map((a) => (
              <option key={a} value={a}>
                {a.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} className={BTN_SM}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </p>
      )}

      {list ? (
        <>
          <AutonomyBanner on={list.autonomy} />
          <StatusCounts counts={list.counts} />
          <SourceTable list={list} onOpen={onOpen} />
        </>
      ) : (
        loading && <p className="text-sm text-muted">Loading…</p>
      )}

      <section className="space-y-2" aria-labelledby="changes-title">
        <h2 id="changes-title" className="font-display text-base font-semibold">
          Recent changes (30 days)
        </h2>
        {changesError && (
          <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
            {changesError}
          </p>
        )}
        {changes && (
          <ChangeList
            changes={changes}
            errors={revertErrors}
            reverting={reverting}
            onRevert={(id) => void revert(id)}
            onOpen={onOpen}
            label="Recent changes (30 days)"
          />
        )}
      </section>

      {openDomain && <SourceCard />}
    </section>
  );
}
