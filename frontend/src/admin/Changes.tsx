/** Spec 011 T118 (US6, FR-021): the Changes screen — every automatic change of every agent in one list (the engine
 * journal and the registry journal): when, who, which object, from → to, status, the one-sentence explanation. */
import { useEffect, useId } from "react";
import { cx } from "../lib/util";
import type { JournalFilter } from "./api";
import { ChangeCard } from "./ChangeCard";
import type { JournalChange } from "./schemas";
import { BTN_SM, when } from "./Sources";
import { useAdmin } from "./store";

const AGENTS = ["parser_doctor", "rule_auditor", "extractor_tuner", "scout", "system", "owner"];
const KINDS = ["parser", "prompt", "role_model", "rule", "source"];
const STATUSES = [
  "proposed",
  "replay",
  "shadow",
  "accepted",
  "watch",
  "kept",
  "held",
  "rejected",
  "abandoned",
  "rolled_back",
  "reverted",
];

const STATUS_CLS: Record<string, string> = {
  proposed: "bg-accent2/15 text-accent2",
  replay: "bg-accent2/15 text-accent2",
  shadow: "bg-accent2/15 text-accent2",
  watch: "bg-warn/15 text-warn",
  accepted: "bg-good/15 text-good",
  kept: "bg-good/15 text-good",
  rejected: "bg-panel2 text-muted",
  abandoned: "bg-panel2 text-muted",
  held: "bg-panel2 text-muted",
  rolled_back: "bg-bad/15 text-bad",
  reverted: "bg-bad/15 text-bad",
};

export function ChangeStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-semibold",
        STATUS_CLS[status] ?? "bg-panel2 text-muted",
      )}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function OriginBadge({ origin }: { origin: string }) {
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px]",
        origin === "engine" ? "border-accent/50 text-accent" : "border-accent2/50 text-accent2",
      )}
    >
      {origin}
    </span>
  );
}

/** "km77@v4 → km77@v5", "candidate → active", or nothing. */
export function fromTo(c: { from_version?: string | null; to_version?: string | null }): string {
  if (!c.from_version && !c.to_version) return "";
  if (c.from_version === c.to_version) return c.to_version ?? "";
  return `${c.from_version ?? "—"} → ${c.to_version ?? "—"}`;
}

export function JournalItem({ c, onOpen }: { c: JournalChange; onOpen?: (id: string) => void }) {
  const ft = fromTo(c);
  return (
    <li className="space-y-1 rounded-lg border border-line/70 p-2.5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        <time className="text-muted" dateTime={c.created_at ?? undefined}>
          {when(c.created_at)}
        </time>
        <OriginBadge origin={c.origin} />
        <ChangeStatusBadge status={c.status} />
        {c.author && <span className="text-muted">by {c.author}</span>}
        <span className="font-medium">
          {c.object_kind}: {c.object_key}
        </span>
        {ft && <span className="font-mono text-muted">{ft}</span>}
        {onOpen && (
          <button
            type="button"
            className={cx(BTN_SM, "ml-auto")}
            onClick={() => onOpen(c.id)}
            aria-label={`Open the change of ${c.object_kind} ${c.object_key}`}
          >
            Open
          </button>
        )}
      </div>
      {c.explanation && <p className="break-words text-sm">{c.explanation}</p>}
    </li>
  );
}

export function JournalList({ changes, onOpen }: { changes: JournalChange[]; onOpen?: (id: string) => void }) {
  if (changes.length === 0) return <p className="text-sm text-muted">No changes in 30 days.</p>;
  return (
    <ol className="space-y-2" aria-label="Changes">
      {changes.map((c) => (
        <JournalItem key={c.id} c={c} onOpen={onOpen} />
      ))}
    </ol>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: string[];
  onChange: (v: string) => void;
}) {
  const id = useId();
  return (
    <span className="inline-flex items-center gap-1">
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-line bg-panel2 px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
      >
        <option value="">all</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o.replace(/_/g, " ")}
          </option>
        ))}
      </select>
    </span>
  );
}

export function JournalFilters({ filter, onChange }: { filter: JournalFilter; onChange: (f: JournalFilter) => void }) {
  const put = (k: keyof JournalFilter) => (v: string) => onChange({ ...filter, [k]: v || undefined });
  return (
    <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Filters">
      <Select label="Origin" value={filter.origin} options={["engine", "registry"]} onChange={put("origin")} />
      <Select label="Agent" value={filter.agent} options={AGENTS} onChange={put("agent")} />
      <Select label="Object" value={filter.object_kind} options={KINDS} onChange={put("object_kind")} />
      <Select label="Status" value={filter.status} options={STATUSES} onChange={put("status")} />
    </div>
  );
}

export function Changes() {
  const rows = useAdmin((s) => s.journal);
  const filter = useAdmin((s) => s.journalFilter);
  const loading = useAdmin((s) => s.journalLoading);
  const error = useAdmin((s) => s.journalError);
  const openId = useAdmin((s) => s.openChangeId);
  const load = useAdmin((s) => s.loadJournal);
  const setFilter = useAdmin((s) => s.setJournalFilter);
  const open = useAdmin((s) => s.openChange);

  useEffect(() => {
    if (useAdmin.getState().journal === null) void load();
  }, [load]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <JournalFilters filter={filter} onChange={(f) => void setFilter(f)} />
        <button type="button" onClick={() => void load()} disabled={loading} className={BTN_SM}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </p>
      )}
      {rows ? <JournalList changes={rows} onOpen={(id) => void open(id)} /> : loading && <p className="text-sm text-muted">Loading…</p>}
      {openId && <ChangeCard />}
    </section>
  );
}
