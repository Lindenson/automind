import { useChat } from "../store/chat";
import { LANGS, asLang, useLang } from "../i18n";
import type { ConnState } from "../lib/transport";
import { cx } from "../lib/util";
import { useCasePanel } from "../store/case";
import { Logo } from "./Logo";
import { PlusIcon } from "./icons";

const CONN: Record<ConnState, { label: string; dot: string }> = {
  open: { label: "Connected", dot: "bg-good" },
  connecting: { label: "Connecting…", dot: "bg-warn animate-pulse" },
  closed: { label: "Reconnecting…", dot: "bg-bad animate-pulse" },
  mock: { label: "Mock mode", dot: "bg-accent2" },
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
  const c = CONN[conn];
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
              Your car expert
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <LangSwitch />
          <span
            className="flex items-center gap-1.5 rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 text-xs text-muted"
            role="status"
          >
            <span className={cx("h-2 w-2 rounded-full", c.dot)} />
            <span className="hidden min-[400px]:inline">{c.label}</span>
          </span>
          <button
            type="button"
            onClick={onOpenChats}
            className="rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 sm:px-3 text-xs font-medium text-fg transition hover:border-accent/60 hover:text-accent"
          >
            Chats
          </button>
          <CaseToggle />
          <button
            type="button"
            onClick={onNewChat}
            disabled={!canReset}
            aria-label="New chat"
            title="New chat"
            className="flex items-center gap-1.5 rounded-full border border-line/70 bg-panel/70 px-2.5 py-1 text-xs font-medium sm:px-3 text-fg transition hover:border-accent/60 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40"
          >
            <PlusIcon />
            <span className="hidden sm:inline">New chat</span>
          </button>
        </div>
      </div>
    </header>
  );
}

function CaseToggle() {
  const { open, setOpen } = useCasePanel();
  return (
    <button
      type="button"
      aria-pressed={open}
      onClick={() => setOpen(!open)}
      className={cx(
        "rounded-full border px-2.5 py-1 text-xs font-medium transition sm:px-3",
        open
          ? "border-accent/60 text-accent"
          : "border-line/70 bg-panel/70 text-fg hover:border-accent/60 hover:text-accent",
      )}
    >
      Your case
    </button>
  );
}

/** Interface language (spec 004 FR-024): follows the conversation unless chosen here. */
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
