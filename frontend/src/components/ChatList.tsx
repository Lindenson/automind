/** Past chats (FR-045): a drawer to reopen and continue earlier conversations. */
import { useEffect, useState } from "react";
import { cx } from "../lib/util";
import { useChat } from "../store/chat";

type ChatRow = {
  id: string;
  title: string;
  updated_at: string;
  cars: string[];
  persona: string;
};

export function ChatList({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const current = useChat((s) => s.chatId);
  const openChat = useChat((s) => s.openChat);
  const [rows, setRows] = useState<ChatRow[] | null>(null);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    fetch("/api/v1/chats", {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    })
      .then((r) => (r.ok ? r.json() : { chats: [] }))
      .then((d: { chats?: ChatRow[] }) => setRows(d.chats ?? []))
      .catch(() => setRows([]));
    return () => ctrl.abort();
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40"
      role="dialog"
      aria-modal="true"
      aria-label="Past chats"
    >
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <aside className="scroll-thin absolute inset-y-0 left-0 w-80 max-w-[85vw] overflow-y-auto border-r border-line/60 bg-bg p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-bold">Your chats</h2>
          <button
            type="button"
            className="text-sm text-muted"
            onClick={onClose}
          >
            Close
          </button>
        </div>
        {rows === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted">No chats yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => {
                    openChat(c.id);
                    onClose();
                  }}
                  className={cx(
                    "w-full rounded-lg border px-3 py-2 text-left text-sm transition hover:border-accent/60",
                    c.id === current
                      ? "border-accent/60 bg-accent/5"
                      : "border-line/50",
                  )}
                >
                  <div className="truncate font-medium">{c.title}</div>
                  <div className="truncate text-xs text-muted">
                    {c.cars.join(" · ") || "no cars yet"} ·{" "}
                    {new Date(c.updated_at).toLocaleDateString()}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
