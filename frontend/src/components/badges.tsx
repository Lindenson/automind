import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import type { Confidence, Provenance, SourceRef } from "../lib/protocol";
import { cx, fmtDate, hostOf } from "../lib/util";

const PROV: Record<Provenance, { short: string; full: string; cls: string }> = {
  MANUFACTURER_CLAIM: {
    short: "Claim",
    full: "Manufacturer claim",
    cls: "text-sky-400 border-sky-400/30 bg-sky-400/10",
  },
  MEASURED: {
    short: "Measured",
    full: "Measured (instrumented test)",
    cls: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
  },
  SOURCED_FACT: {
    short: "Sourced",
    full: "Sourced fact",
    cls: "text-indigo-300 border-indigo-300/30 bg-indigo-300/10",
  },
  DERIVED: {
    short: "Derived",
    full: "Derived (calculated from other values)",
    cls: "text-violet-300 border-violet-300/30 bg-violet-300/10",
  },
  SIMULATED_ESTIMATE: {
    short: "Simulated",
    full: "Simulated estimate",
    cls: "text-orange-400 border-orange-400/30 bg-orange-400/10",
  },
  ASSUMPTION: {
    short: "Assumption",
    full: "Assumption",
    cls: "text-amber-400 border-amber-400/40 bg-amber-400/10",
  },
};

export function ProvenanceBadge({ p }: { p: Provenance }) {
  const d = PROV[p];
  return (
    <span
      title={d.full}
      className={cx(
        "inline-flex shrink-0 items-center rounded border px-1 py-px text-[10px] font-semibold uppercase tracking-wide",
        d.cls,
      )}
    >
      {d.short}
    </span>
  );
}

export function AssumptionBadge() {
  return <ProvenanceBadge p="ASSUMPTION" />;
}

const CONF: Record<Confidence, string> = {
  HIGH: "bg-good",
  MEDIUM: "bg-warn",
  LOW: "bg-bad",
};

export function ConfidenceDot({ c }: { c: Confidence }) {
  return (
    <span
      className="inline-flex shrink-0 items-center"
      title={`Confidence: ${c.toLowerCase()}`}
      aria-label={`confidence ${c.toLowerCase()}`}
    >
      <span
        className={cx(
          "h-2 w-2 rounded-full ring-2 ring-panel",
          CONF[c],
          c === "LOW" && "animate-pulse",
        )}
      />
    </span>
  );
}

const SRC_TYPE: Record<SourceRef["type"], string> = {
  MANUFACTURER: "Manufacturer",
  INSTRUMENTED_TEST: "Instrumented test",
  PUBLICATION: "Publication",
  ENCYCLOPEDIA: "Encyclopedia",
  SPEC_DATABASE: "Spec database",
};

export function sourceTypeLabel(t: SourceRef["type"]) {
  return SRC_TYPE[t];
}

export function SourceItem({
  s,
  compact,
}: {
  s: SourceRef;
  compact?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <a
          href={s.url}
          target="_blank"
          rel="noreferrer noopener"
          className="min-w-0 break-words font-medium text-fg hover:text-accent2"
        >
          {s.name}
        </a>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-muted">
        <span className="rounded bg-panel2 px-1.5 py-px">
          {sourceTypeLabel(s.type)}
        </span>
        <span>{hostOf(s.url)}</span>
        <span>· retrieved {fmtDate(s.retrieved_at)}</span>
      </div>
      {s.excerpt && (
        <p
          className={cx(
            "mt-1.5 border-l-2 border-accent/50 pl-2 text-xs italic text-muted",
            compact && "line-clamp-3",
          )}
        >
          “{s.excerpt}”
        </p>
      )}
    </div>
  );
}

/** Small "n sources" button with a viewport-clamped popover rendered in a portal. */
export function SourcesButton({ sources }: { sources: SourceRef[] }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const place = () => {
      const r = btn.current!.getBoundingClientRect();
      const w = Math.min(340, window.innerWidth - 24);
      const h = pop.current?.offsetHeight ?? 200;
      let left = r.left + r.width / 2 - w / 2;
      left = Math.max(12, Math.min(left, window.innerWidth - w - 12));
      let top = r.bottom + 8;
      if (top + h > window.innerHeight - 12 && r.top - h - 8 > 12)
        top = r.top - h - 8;
      setPos({ top, left });
    };
    place();
    const raf = requestAnimationFrame(place);
    return () => cancelAnimationFrame(raf);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node | null;
      if (t && (pop.current?.contains(t) || btn.current?.contains(t))) return;
      setOpen(false);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const scroll = (e: Event) => {
      if (
        pop.current &&
        e.target instanceof Node &&
        pop.current.contains(e.target)
      )
        return;
      setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("touchstart", close);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", scroll, true);
    window.addEventListener("resize", scroll);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("touchstart", close);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", scroll, true);
      window.removeEventListener("resize", scroll);
    };
  }, [open]);

  if (sources.length === 0) return null;
  return (
    <>
      <button
        ref={btn}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="Show sources"
        className={cx(
          "inline-flex shrink-0 items-center gap-0.5 rounded px-1 py-px text-[10px] font-semibold text-muted transition hover:bg-panel2 hover:text-accent2",
          open && "bg-panel2 text-accent2",
        )}
      >
        <LinkIcon />
        {sources.length}
      </button>
      {open &&
        createPortal(
          <div
            ref={pop}
            role="dialog"
            style={{
              top: pos?.top ?? -9999,
              left: pos?.left ?? -9999,
              width: Math.min(340, window.innerWidth - 24),
            }}
            className="card fixed z-50 max-h-[60vh] animate-fadeUp overflow-y-auto p-3 text-sm scroll-thin"
          >
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
              {sources.length === 1 ? "Source" : `${sources.length} sources`}
            </div>
            <div className="space-y-3">
              {sources.map((s, i) => (
                <SourceItem key={i} s={s} />
              ))}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

function LinkIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-3 w-3"
      aria-hidden
    >
      <path
        d="M8.5 11.5a3.5 3.5 0 0 0 5 0l2.5-2.5a3.5 3.5 0 0 0-5-5L10 5"
        strokeLinecap="round"
      />
      <path
        d="M11.5 8.5a3.5 3.5 0 0 0-5 0L4 11a3.5 3.5 0 0 0 5 5l1-1"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function BlockCard({
  title,
  icon,
  right,
  children,
  className,
}: {
  title?: string;
  icon?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx("card min-w-0 animate-fadeUp overflow-hidden", className)}
    >
      {title && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 px-4 py-2.5">
          <h3 className="flex min-w-0 items-center gap-2 font-display text-sm font-semibold tracking-tight">
            {icon && <span className="text-accent">{icon}</span>}
            <span className="truncate">{title}</span>
          </h3>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function CarSwatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
      style={{ background: color }}
    />
  );
}
