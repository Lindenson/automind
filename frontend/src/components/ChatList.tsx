/** Past chats (FR-045): a drawer to reopen and continue earlier conversations. */
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { deleteChats } from "../lib/chats";
import { cx, useEscape } from "../lib/util";
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
  const newChat = useChat((s) => s.newChat);
  const [rows, setRows] = useState<ChatRow[] | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const t = useT();
  useEscape(open, onClose);

  const remove = async (ids: string[]) => {
    if (ids.length === 0) return;
    const question =
      ids.length === 1 ? t("chats.confirmOne") : t("chats.confirmMany", { n: ids.length });
    if (!window.confirm(question)) return;
    const before = rows;
    setRows((r) => (r ? r.filter((c) => !ids.includes(c.id)) : r)); // optimistic
    setError(null);
    try {
      await deleteChats(ids);
      setSelected(new Set());
      setSelecting(false);
      if (ids.includes(current)) newChat();
    } catch {
      setRows(before); // roll back
      setError(t("chats.deleteFailed"));
    }
  };

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

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
      aria-label={t("chats.aria")}
    >
      <button
        type="button"
        aria-label={t("chats.close")}
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      <aside className="scroll-thin absolute inset-y-0 left-0 w-80 max-w-[85vw] overflow-y-auto border-r border-line/60 bg-bg p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-display text-sm font-bold">{t("chats.title")}</h2>
          <div className="flex items-center gap-3">
            {rows && rows.length > 0 && (
              <button
                type="button"
                className="text-xs text-muted hover:text-fg"
                onClick={() => {
                  setSelecting(!selecting);
                  setSelected(new Set());
                }}
              >
                {selecting ? t("chats.cancel") : t("chats.select")}
              </button>
            )}
            <button type="button" className="text-sm text-muted" onClick={onClose}>
              {t("chats.close")}
            </button>
          </div>
        </div>
        {selecting && (
          <button
            type="button"
            disabled={selected.size === 0}
            onClick={() => void remove([...selected])}
            className="mb-3 w-full rounded-lg bg-bad/80 px-3 py-1.5 text-sm font-semibold text-bg disabled:opacity-40"
          >
            {t("chats.deleteSelected", { n: selected.size })}
          </button>
        )}
        {error && <p className="mb-2 text-xs text-bad">{error}</p>}
        {rows === null ? (
          <p className="text-sm text-muted">{t("chats.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted">{t("chats.none")}</p>
        ) : (
          <ul className="space-y-1.5">
            {rows.map((c) => (
              <li key={c.id} className="group flex items-center gap-2">
                {selecting && (
                  <input
                    type="checkbox"
                    aria-label={t("chats.selectOne", { title: c.title })}
                    checked={selected.has(c.id)}
                    onChange={() => toggle(c.id)}
                  />
                )}
                <button
                  type="button"
                  onClick={() => {
                    if (selecting) return toggle(c.id);
                    openChat(c.id);
                    onClose();
                  }}
                  className={cx(
                    "min-w-0 flex-1 rounded-lg border px-3 py-2 text-left text-sm transition hover:border-accent/60",
                    c.id === current
                      ? "border-accent/60 bg-accent/5"
                      : "border-line/50",
                  )}
                >
                  <div className="truncate font-medium">{c.title}</div>
                  <div className="truncate text-xs text-muted">
                    {c.cars.join(" · ") || t("chats.noCars")} ·{" "}
                    {new Date(c.updated_at).toLocaleDateString()}
                  </div>
                </button>
                {!selecting && (
                  <button
                    type="button"
                    aria-label={t("chats.deleteOne", { title: c.title })}
                    title={t("chats.deleteTitle")}
                    onClick={() => void remove([c.id])}
                    className="shrink-0 rounded p-1 text-xs text-muted opacity-60 hover:text-bad hover:opacity-100 group-hover:opacity-100"
                  >
                    ✕
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
