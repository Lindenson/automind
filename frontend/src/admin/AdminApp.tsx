/** Spec 010 T044 (US4): the admin page — Top problems and Sources; spec 011 T116 adds Parsers, Changes, Accuracy
 * and the engine status strip in the header. The rest lives in Prometheus. */
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Logo } from "../components/Logo";
import { cx, fmtNum } from "../lib/util";
import { Accuracy } from "./Accuracy";
import { Changes } from "./Changes";
import { Parsers } from "./Parsers";
import { Problems } from "./Problems";
import type { EngineStatus } from "./schemas";
import { Sources } from "./Sources";
import { useAdmin, type AdminTab } from "./store";

const TABS: { id: AdminTab; label: string }[] = [
  { id: "problems", label: "Top problems" },
  { id: "sources", label: "Sources" },
  { id: "parsers", label: "Parsers" },
  { id: "changes", label: "Changes" },
  { id: "accuracy", label: "Accuracy" },
];

/** "12 s", "5 min", "3 h". */
export function age(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

/** Worker beat age, open changes, today's spend against the budgets. */
export function EngineStrip({ e }: { e: EngineStatus | null }) {
  if (!e) return null;
  const budgets = Object.values(e.budgets_today);
  const spent = budgets.reduce((a, b) => a + b.spent, 0);
  const limit = budgets.reduce((a, b) => a + (b.limit ?? 0), 0);
  const stale = !e.worker || (e.worker.age_s ?? Infinity) > 300;
  return (
    <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted" aria-label="Engine status">
      <li className={cx(stale && "font-semibold text-bad")}>
        {e.worker ? `worker beat ${age(e.worker.age_s ?? 0)} ago` : "no worker"}
      </li>
      <li>
        {e.open_changes} open {e.open_changes === 1 ? "change" : "changes"}
      </li>
      <li title={Object.entries(e.budgets_today).map(([k, b]) => `${k}: €${fmtNum(b.spent, 4)} / ${b.limit ?? "∞"}`).join("\n")}>
        budgets €{fmtNum(spent, 2)} / €{fmtNum(limit, 2)} today
      </li>
      <li>autonomy {e.autonomy ? "on" : "off"}</li>
    </ul>
  );
}

function Screen({ tab }: { tab: AdminTab }) {
  switch (tab) {
    case "sources":
      return <Sources />;
    case "parsers":
      return <Parsers />;
    case "changes":
      return <Changes />;
    case "accuracy":
      return <Accuracy />;
    default:
      return <Problems />;
  }
}

export function TokenPrompt({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [token, setToken] = useState("");
  return (
    <form
      className="card mx-auto max-w-sm space-y-3 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (token.trim()) onSubmit(token);
      }}
    >
      <h2 className="font-display text-lg font-semibold">Admin token</h2>
      <p className="text-sm text-muted">Access was refused. Enter the admin token to continue.</p>
      <label htmlFor="admin-token" className="sr-only">
        Admin token
      </label>
      <input
        id="admin-token"
        type="password"
        autoComplete="current-password"
        autoFocus
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="w-full rounded-md border border-line bg-panel2 px-3 py-2 font-mono text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
      />
      <button
        type="submit"
        disabled={!token.trim()}
        className="w-full rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white hover:bg-accent/90 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2"
      >
        Continue
      </button>
    </form>
  );
}

export default function AdminApp() {
  const tab = useAdmin((s) => s.tab);
  const setTab = useAdmin((s) => s.setTab);
  const needToken = useAdmin((s) => s.needToken);
  const submitToken = useAdmin((s) => s.submitToken);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const engine = useAdmin((s) => s.engine);
  const loadEngine = useAdmin((s) => s.loadEngine);

  useEffect(() => {
    void loadEngine();
    const t = window.setInterval(() => void loadEngine(), 60_000);
    return () => window.clearInterval(t);
  }, [loadEngine]);

  const onTabKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = (i + d + TABS.length) % TABS.length;
    setTab(TABS[next]!.id);
    tabRefs.current[next]?.focus();
  };

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-line/70 bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center gap-3 px-4 py-3">
          <a href="/" aria-label="Back to the chat" className="rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2">
            <Logo small />
          </a>
          <h1 className="font-display text-base font-semibold">
            AutoMind <span className="text-muted">admin</span>
          </h1>
          <div className="ml-auto min-w-0">
            <EngineStrip e={engine} />
          </div>
        </div>
        <div className="mx-auto max-w-4xl px-4">
          <div role="tablist" aria-label="Admin screens" className="flex gap-1 overflow-x-auto">
            {TABS.map((t, i) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                id={`tab-${t.id}`}
                role="tab"
                type="button"
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                tabIndex={tab === t.id ? 0 : -1}
                onClick={() => setTab(t.id)}
                onKeyDown={(e) => onTabKey(e, i)}
                className={cx(
                  "-mb-px border-b-2 px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-accent2",
                  tab === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-4">
        {needToken ? (
          <TokenPrompt onSubmit={(t) => void submitToken(t)} />
        ) : (
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            <Screen tab={tab} />
          </div>
        )}
      </main>
    </div>
  );
}
