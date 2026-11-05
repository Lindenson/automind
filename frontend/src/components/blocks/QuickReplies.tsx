import { useT } from "../../i18n";
import type { Block } from "../../lib/protocol";
import { useChat } from "../../store/chat";

type B = Extract<Block, { type: "quick_replies" }>;

/** The composer's text box (a "type it" chip puts the cursor there instead of sending). */
export function focusComposer(): void {
  document.querySelector<HTMLTextAreaElement>("form textarea")?.focus();
}

/**
 * One-tap answers under a question: each sends its text as the user's message (spec 004 FR-031). Styled as the
 * user's own reply bubbles, so they read as answers, not as next actions (audit F11).
 */
export function QuickReplies({ b }: { b: B }) {
  const t = useT();
  const send = useChat((s) => s.send);
  const busy = useChat((s) => Boolean(s.pending));
  if (!b.items.length) return null;
  return (
    <div className="space-y-2" data-testid="quick-replies">
      {b.question && <p className="text-sm">{b.question}</p>}
      <div className="flex flex-wrap items-center justify-end gap-2" role="group" aria-label={t("quick.aria")}>
        <span className="text-xs text-muted">{t("quick.label")}</span>
        {b.items.map((it) => (
          <button
            key={it.label}
            type="button"
            disabled={busy}
            title={it.reason ?? undefined}
            onClick={() => (it.typing ? focusComposer() : send(it.text))}
            className={`min-h-11 rounded-2xl rounded-br-md border px-4 py-2 text-left text-sm hover:border-accent/60 disabled:opacity-50 ${
              it.suggested
                ? "border-accent/60 bg-accent/10"
                : it.typing
                  ? "border-dashed border-accent/30"
                  : "border-accent/30 bg-accent/5"
            }`}
          >
            {it.label}
            {it.suggested && it.reason && <span className="block text-xs text-muted">{it.reason}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
