/** Spec 010 T045 (FR-026): the ranked list of the 10 highest-impact open issues. */
import { useEffect } from "react";
import { fmtNum } from "../lib/util";
import { FixBadge, StatusBadge, frequency } from "./badges";
import { CopyButton } from "./CopyButton";
import { ProblemCard } from "./ProblemCard";
import type { ProblemItem } from "./schemas";
import { useAdmin } from "./store";

export function ProblemRow({ p, onOpen }: { p: ProblemItem; onOpen: (id: string) => void }) {
  return (
    <li
      className="card flex cursor-pointer gap-3 p-3 transition hover:border-line sm:p-4"
      onClick={() => onOpen(p.id)}
    >
      <div className="w-7 shrink-0 pt-0.5 text-right font-display text-lg font-semibold text-muted">{p.rank}</div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpen(p.id);
            }}
            className="min-w-0 text-left font-medium hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
          >
            {p.title}
          </button>
          <StatusBadge status={p.status} />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          <span>{frequency(p.failing_turns_7d, p.chats_7d)}</span>
          <span>impact {fmtNum(p.impact, 1)}</span>
          {p.component && <span className="chip">{p.component}</span>}
          {p.example_chat && (
            <span className="inline-flex items-center gap-1">
              chat <code className="font-mono text-fg">{p.example_chat.slice(0, 8)}</code>
              <CopyButton
                text={p.example_chat}
                label="copy"
                copiedLabel="✓"
                ariaLabel={`Copy chat id ${p.example_chat}`}
                className="px-1.5 py-0 text-[11px]"
              />
            </span>
          )}
        </div>
        <FixBadge fix={p.fix} />
      </div>
    </li>
  );
}

export function ProblemList({ items, onOpen }: { items: ProblemItem[]; onOpen: (id: string) => void }) {
  if (items.length === 0) return <p className="card p-6 text-center text-sm text-muted">No open problems.</p>;
  return (
    <ol className="space-y-2" aria-label="Top problems">
      {items.map((p) => (
        <ProblemRow key={p.id} p={p} onOpen={onOpen} />
      ))}
    </ol>
  );
}

export function Problems() {
  const problems = useAdmin((s) => s.problems);
  const loading = useAdmin((s) => s.loading);
  const error = useAdmin((s) => s.error);
  const openId = useAdmin((s) => s.openId);
  const load = useAdmin((s) => s.loadProblems);
  const open = useAdmin((s) => s.openProblem);

  useEffect(() => {
    if (useAdmin.getState().problems === null) void load();
  }, [load]);

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted">The 10 open issues with the highest impact in the last 7 days.</p>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="shrink-0 rounded-md border border-line px-2.5 py-1 text-xs hover:bg-panel2 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </p>
      )}
      {problems ? (
        <ProblemList items={problems} onOpen={(id) => void open(id)} />
      ) : (
        loading && <p className="text-sm text-muted">Loading…</p>
      )}
      {openId && <ProblemCard />}
    </section>
  );
}
