import { useChat } from "../store/chat";
import { LANGS, UI_LANG, asLang, useLang, useT } from "../i18n";
import type { Key } from "../i18n/en";
import type { ConnState } from "../lib/transport";
import { cx } from "../lib/util";
import { useCasePanel } from "../store/case";
import { Logo } from "./Logo";
import { PlusIcon } from "./icons";

const CONN: Record<ConnState, { label: Key; dot: string }> = {
  open: { label: "conn.open", dot: "bg-good" },
  connecting: { label: "conn.connecting", dot: "bg-warn animate-pulse" },
  closed: { label: "conn.closed", dot: "bg-bad animate-pulse" },
  gone: { label: "conn.gone", dot: "bg-bad" },
  mock: { label: "conn.mock", dot: "bg-accent2" },
};

export function Header({
  conn,
  onNewChat,
  canReset,
  onOpenChats,
}: {
  conn: ConnState;
  onNewChat: () => void;
  canReset: boolean;
  onOpenChats: () => void;
}) {
  const t = useT();
  const c = CONN[conn];
  const attempt = useChat((s) => s.connAttempt);
  return (
    <header className="sticky top-0 z-30 border-b border-line/60 bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-4xl items-center justify-between gap-3 px-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <Logo />
          <div className="hidden min-w-0 leading-tight min-[440px]:block">
            <div className="font-display text-base font-bold tracking-tight">
              Auto<span className="text-accent">Mind</span>
            </div>
            <div className="hidden truncate text-[11px] text-muted sm:block">
              {t("header.tagline")}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          {UI_LANG === null && <LangSwitch />}
          <span
            className="flex items-center gap-1.5 rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 text-xs text-muted"
            role="status"
            aria-label={t(c.label)}
          >
            <span className={cx("h-2 w-2 rounded-full", c.dot)} />
            <span className="hidden min-[400px]:inline">{t(c.label)}</span>
          </span>
          <button
            type="button"
            onClick={onOpenChats}
            className="rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 sm:px-3 text-xs font-medium text-fg transition hover:border-accent/60 hover:text-accent"
          >
            {t("header.chats")}
          </button>
          <CaseToggle />
          <button
            type="button"
            onClick={onNewChat}
            disabled={!canReset}
            aria-label={t("header.newChat")}
            title={t("header.newChat")}
            className="flex items-center gap-1.5 rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 text-xs font-medium sm:px-3 text-fg transition hover:border-accent/60 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            <PlusIcon />
            <span className="hidden sm:inline">{t("header.newChat")}</span>
          </button>
        </div>
      </div>
      <ConnBanner conn={conn} attempt={attempt} onNewChat={onNewChat} />
    </header>
  );
}

/** A lost or refused connection in words, with the one thing to do about it (audit F8). */
export function ConnBanner({
  conn,
  attempt,
  onNewChat,
}: {
  conn: ConnState;
  /** reconnect attempts so far */
  attempt: number;
  onNewChat: () => void;
}) {
  const t = useT();
  const reconnect = useChat((s) => s.reconnect);
  if (conn !== "closed" && conn !== "gone") return null;
  const gone = conn === "gone";
  return (
    <div
      role="status"
      data-testid="conn-banner"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-t border-bad/30 bg-bad/10 px-4 py-1.5 text-center text-xs text-fg"
    >
      <span>
        {gone ? t("conn.gone.banner") : t("conn.banner")}
        {!gone && attempt > 0 && <span className="text-muted"> ({t("conn.attempt", { n: attempt })})</span>}
      </span>
      <button
        type="button"
        onClick={gone ? onNewChat : reconnect}
        className="min-h-8 rounded-full border border-line/70 bg-panel px-3 py-0.5 font-medium hover:border-accent/60"
      >
        {gone ? t("error.action.newChat") : t("conn.retry")}
      </button>
    </div>
  );
}

export function CaseToggle() {
  const t = useT();
  const { open, setOpen, unseen } = useCasePanel();
  return (
    <button
      type="button"
      aria-pressed={open}
      aria-label={unseen > 0 ? `${t("header.case")} — ${t("header.case.unseen", { n: unseen })}` : undefined}
      onClick={() => setOpen(!open)}
      className={cx(
        "relative rounded-full border px-2.5 py-1 text-xs font-medium transition sm:px-3",
        open
          ? "border-accent/60 text-accent"
          : "border-line/70 bg-panel/70 text-fg hover:border-accent/60 hover:text-accent",
      )}
    >
      {t("header.case")}
      {unseen > 0 && !open && (
        // spec 010 FR-038: changes arrived since the panel was last looked at
        <span
          aria-hidden
          data-testid="case-unseen"
          className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-solid px-1 text-[10px] font-bold text-on-accent"
        >
          {unseen > 9 ? "9+" : unseen}
        </span>
      )}
    </button>
  );
}

/** Interface language (spec 004 FR-024): follows the conversation unless chosen here.
 *  Hidden while the interface is pinned to English (`UI_LANG`, spec 010 FR-042). */
function LangSwitch() {
  const lang = useLang();
  const manual = useChat((s) => s.manualLang);
  const setLang = useChat((s) => s.setLang);
  return (
    <select
      aria-label="Language"
      value={manual ?? ""}
      onChange={(e) => setLang(asLang(e.target.value))}
      className="min-h-9 rounded-full border border-line/70 bg-panel/70 px-2 text-xs"
      title={lang.toUpperCase()}
    >
      <option value="">{`Auto (${lang.toUpperCase()})`}</option>
      {LANGS.map((l) => (
        <option key={l} value={l}>
          {l.toUpperCase()}
        </option>
      ))}
    </select>
  );
}
