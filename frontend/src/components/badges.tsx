import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import type { Confidence, Provenance, SourceRef } from "../lib/protocol";
import { useT } from "../i18n";
import { cx, fmtDate, hostOf } from "../lib/util";
import { badSourceKey, useChat, type BadSourceState } from "../store/chat";

/** The assistant message whose blocks are being rendered (spec 010 US2: "bad source" needs it). */
export const MessageIdContext = createContext<string | null>(null);

/** Where a source was cited: lets a "bad source" mark be tied to a value (all optional). */
export interface SourceWhere {
  messageId?: string;
  carId?: string;
  attribute?: string;
  area?: string;
}

/** Theme tokens (`--prov-*` in index.css) with light variants: readable in both themes (audit F5). */
const PROV: Record<Provenance, string> = {
  MANUFACTURER_CLAIM: "text-prov-claim border-prov-claim/40 bg-prov-claim/10",
  MEASURED: "text-prov-measured border-prov-measured/40 bg-prov-measured/10",
  SOURCED_FACT: "text-prov-sourced border-prov-sourced/40 bg-prov-sourced/10",
  DERIVED: "text-prov-derived border-prov-derived/40 bg-prov-derived/10",
  SIMULATED_ESTIMATE: "text-prov-simulated border-prov-simulated/40 bg-prov-simulated/10",
  ASSUMPTION: "text-prov-assumption border-prov-assumption/40 bg-prov-assumption/10",
};

/** Basis of an understood value (intake card, case panel): theme tokens `--basis-*`. */
export const BASIS_CLS: Record<string, string> = {
  STATED: "border-basis-stated/50 text-basis-stated",
  INFERRED: "border-basis-inferred/50 text-basis-inferred",
  LOOKED_UP: "border-basis-found/50 text-basis-found",
  ASSUMED: "border-basis-assumed/50 text-basis-assumed",
};

export function ProvenanceBadge({ p }: { p: Provenance }) {
  const t = useT();
  return (
    <span
      title={t(`prov.${p}.full` as "prov.MEASURED.full")}
      className={cx(
        "inline-flex shrink-0 items-center rounded border px-1 py-px text-[10px] font-semibold uppercase tracking-wide",
        PROV[p],
      )}
    >
      {t(`prov.${p}` as "prov.MEASURED")}
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

const CONF_TEXT: Record<Confidence, string> = {
  HIGH: "text-good",
  MEDIUM: "text-warn",
  LOW: "text-bad",
};

/** Confidence as a dot and as text (spec 010 FR-040): never colour only. */
export function ConfidenceDot({ c }: { c: Confidence }) {
  const t = useT();
  const word = t(`conf.${c}` as "conf.HIGH");
  const label = t("conf.dot", { c: word });
  return (
    <span className="inline-flex shrink-0 items-center gap-1" role="img" aria-label={label}>
      <span
        aria-hidden
        className={cx(
          "h-2 w-2 rounded-full ring-2 ring-panel",
          CONF[c],
          c === "LOW" && "animate-pulse",
        )}
      />
      <span aria-hidden className={cx("text-[10px] font-medium", CONF_TEXT[c])} data-testid="conf-text">
        {word}
      </span>
    </span>
  );
}

/**
 * A reason reachable by tap and keyboard (spec 010 FR-040), instead of a `title` tooltip: the trigger is a button
 * that shows the reason as a visible line below it.
 */
export function Reveal({
  children,
  reason,
  what,
  className,
  as = "span",
  plain = false,
}: {
  children: ReactNode;
  reason?: string | null;
  /** what the reason is about, for the button name */
  what: string;
  className?: string;
  as?: "span" | "li";
  /** no dotted underline (a cell that is already a box) */
  plain?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const Tag = as;
  if (!reason) return <Tag className={className}>{children}</Tag>;
  return (
    <Tag className="inline-flex max-w-full flex-col items-start">
      <button
        type="button"
        aria-expanded={open}
        aria-label={t("reason.aria", { what })}
        onClick={() => setOpen((o) => !o)}
        className={cx(className, "cursor-pointer", !plain && "underline decoration-dotted underline-offset-2")}
      >
        {children}
      </button>
      {open && (
        <span role="note" className="mt-0.5 max-w-xs text-[11px] leading-snug text-muted">
          {reason}
        </span>
      )}
    </Tag>
  );
}


/** spec 010 US2: "bad source" on an accepted source of an answer; "noted ✓" once the server acks. */
export function BadSourceAction({
  url,
  messageId,
  carId,
  attribute,
  area,
}: { url: string; messageId: string } & Omit<SourceWhere, "messageId">) {
  const state = useChat((st) => st.badSources[badSourceKey(messageId, url)]);
  const badSource = useChat((st) => st.badSource);
  return (
    <BadSourceButton
      state={state}
      onClick={() => badSource({ messageId, url, carId, attribute, area })}
    />
  );
}

/** The "bad source" button itself, by state (no store). */
export function BadSourceButton({
  state,
  onClick,
}: {
  state?: BadSourceState;
  onClick?: () => void;
}) {
  const t = useT();
  const label =
    state === "noted"
      ? t("sources.bad.noted")
      : state === "ignored"
        ? t("sources.bad.ignored")
        : t("sources.bad");
  return (
    <button
      type="button"
      disabled={Boolean(state)}
      aria-busy={state === "pending" || undefined}
      aria-label={state ? label : t("sources.bad.aria")}
      title={t("sources.bad.title")}
      onClick={onClick}
      className={cx(
        "inline-flex items-center gap-1 rounded px-1 py-px text-[11px] font-medium text-muted transition hover:bg-panel2 hover:text-bad disabled:cursor-default disabled:hover:bg-transparent",
        state === "noted" && "text-good disabled:hover:text-good",
        state === "pending" && "opacity-70",
        state === "ignored" && "disabled:hover:text-muted",
      )}
    >
      {!state && <FlagIcon />}
      {label}
    </button>
  );
}

function FlagIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-3 w-3"
      aria-hidden
    >
      <path d="M4 18V3m0 1h9l-1.5 3.5L13 11H4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SourceItem({
  s,
  compact,
  messageId,
  carId,
  attribute,
  area,
}: {
  s: SourceRef;
  compact?: boolean;
} & SourceWhere) {
  const t = useT();
  const ctxMessageId = useContext(MessageIdContext);
  const mid = messageId ?? ctxMessageId ?? undefined;
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
          {t(`src.${s.type}` as "src.MANUFACTURER")}
        </span>
        <span>{hostOf(s.url)}</span>
        <span>{t("sources.retrieved", { date: fmtDate(s.retrieved_at) })}</span>
        {!s.rejected && mid && s.url && (
          <BadSourceAction url={s.url} messageId={mid} carId={carId} attribute={attribute} area={area} />
        )}
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

/** Small "n sources" button with a viewport-clamped popover rendered in a portal.
 *  `what` names the value the sources are for (e.g. "0–100 km/h, Golf GTI") for screen readers. */
export function SourcesButton({
  sources,
  what,
  ...where
}: { sources: SourceRef[]; what?: string } & SourceWhere) {
  const t = useT();
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
        aria-label={
          what
            ? t("sources.buttonFor", { what, n: sources.length })
            : t("sources.button", { n: sources.length })
        }
        title={t("sources.show")}
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
              {sources.length === 1 ? t("sources.one") : t("sources.many", { n: sources.length })}
            </div>
            <div className="space-y-3">
              {sources.map((s, i) => (
                <SourceItem key={i} s={s} {...where} />
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
