/** An error line that says what happened and offers one next step (audit F8). */
import { useT } from "../i18n";
import type { Key } from "../i18n/en";
import { messageDomId } from "../lib/scroll";
import { useChat, type ErrorEntry, type ErrorKind } from "../store/chat";
import { WarnIcon } from "./icons";

export type NextAction = "retry" | "ask" | "continue" | "stop" | "reload" | "reconnect" | "newChat";

/** The next step for a kind of failure: one line of advice and at most one action. */
export function nextStep(
  kind: ErrorKind,
  opts: { running: boolean; canRetry: boolean },
): { next: Key; action: NextAction | null } {
  switch (kind) {
    case "overloaded":
      return { next: "error.next.overloaded", action: opts.canRetry ? "retry" : null };
    case "limit":
      return { next: "error.next.limit", action: "continue" };
    case "busy":
      // the research runs on: stop it here, or reload when this page lost track of it
      return { next: "error.next.busy", action: opts.running ? "stop" : "reload" };
    case "stopped":
      return { next: "error.next.stopped", action: opts.canRetry ? "ask" : null };
    case "offline":
      return { next: "error.next.offline", action: "reconnect" };
    case "gone":
      return { next: "error.next.gone", action: "newChat" };
    default:
      return { next: "error.next.generic", action: opts.canRetry ? "retry" : "reload" };
  }
}

const LABEL: Record<NextAction, Key> = {
  retry: "error.action.retry",
  ask: "error.action.ask",
  continue: "error.action.continue",
  stop: "error.action.stop",
  reload: "error.action.reload",
  reconnect: "error.action.reconnect",
  newChat: "error.action.newChat",
};

export function ErrorNotice({ m }: { m: ErrorEntry }) {
  const t = useT();
  const running = useChat((s) => s.pending !== null);
  const connected = useChat((s) => s.conn === "open" || s.conn === "mock");
  const kind = m.kind ?? "generic";
  const { next, action } = nextStep(kind, { running, canRetry: Boolean(m.retry) });

  const run = () => {
    const s = useChat.getState();
    if (action === "retry" || action === "ask") s.send(m.retry ?? "");
    else if (action === "continue") s.send(t("error.action.continue.text"));
    else if (action === "stop") s.cancel();
    else if (action === "reconnect") s.reconnect();
    else if (action === "newChat") s.newChat();
    else if (action === "reload") window.location.reload();
  };
  // sending needs a connection and no running turn; the other actions are always possible
  const sends = action === "retry" || action === "ask" || action === "continue";
  const disabled = sends && (running || !connected);

  return (
    <div
      id={messageDomId(m.message_id)}
      className="flex animate-fadeUp items-start gap-2 rounded-xl border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-sm"
      role="alert"
      data-testid="error"
      data-kind={kind}
    >
      <span className="mt-0.5 text-bad">
        <WarnIcon />
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="break-words">{m.text}</p>
        <p className="text-muted">{t(next)}</p>
        {action && (
          <button
            type="button"
            onClick={run}
            disabled={disabled}
            className="min-h-9 rounded-full border border-line/70 bg-panel px-3 py-1 text-xs font-medium text-fg hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t(LABEL[action])}
          </button>
        )}
      </div>
    </div>
  );
}
