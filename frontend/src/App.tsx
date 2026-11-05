import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CancelButton } from "./components/CancelButton";
import { CaseSheet, CaseSidebar } from "./components/CasePanel/CasePanel";
import { ChatList } from "./components/ChatList";
import { Composer } from "./components/Composer";
import { ConfirmCard } from "./components/ConfirmCard";
import { EmptyState } from "./components/EmptyState";
import { Header } from "./components/Header";
import { Message } from "./components/Message";
import { StatusTimeline } from "./components/StatusTimeline";
import { ProgressGrid } from "./components/ProgressGrid";
import { HistorySchema } from "./lib/protocol";
import {
  createWsTransport,
  loadLastSeq,
  type Transport,
} from "./lib/transport";
import { messageDomId, scrollTarget } from "./lib/scroll";
import { isMockMode } from "./lib/util";
import { loadCase, watchCase } from "./store/case";
import { useChat } from "./store/chat";
import { useT } from "./i18n";

const MOCK = isMockMode();

export default function App() {
  const t = useT();
  const {
    chatId,
    conn,
    messages,
    pending,
    historyLoading,
    send,
    newChat,
    confirm,
  } = useChat();
  const scroller = useRef<HTMLDivElement>(null);
  const [chatsOpen, setChatsOpen] = useState(false);
  const stick = useRef(true);

  // spec 010 FR-038: the case panel opens by itself on wide screens and counts unseen changes
  useEffect(() => watchCase(), []);

  // One transport per chat id.
  useEffect(() => {
    const { handleRaw, setConn, setTransport } = useChat.getState();
    const h = { onMessage: handleRaw, onState: setConn };
    let t: Transport | null = null;
    let cancelled = false;
    if (MOCK) {
      // The mock (and its data) is only downloaded in mock mode.
      void import("./mock/mockTransport").then(({ createMockTransport }) => {
        if (cancelled) return;
        t = createMockTransport(h);
        setTransport(t);
      });
    } else {
      t = createWsTransport(chatId, h, loadLastSeq(chatId));
      setTransport(t);
    }
    return () => {
      cancelled = true;
      t?.close();
      setTransport(null);
    };
  }, [chatId]);

  // Mock-mode convenience: `?mock=1&q=...` asks the question automatically once.
  const transport = useChat((s) => s.transport);
  const autoAsked = useRef(false);
  useEffect(() => {
    if (!MOCK || !transport || autoAsked.current) return;
    const q = new URLSearchParams(window.location.search).get("q");
    if (!q) return;
    autoAsked.current = true;
    send(q);
  }, [transport, send]);

  // History on (re)load.
  useEffect(() => {
    if (MOCK) return;
    const ctrl = new AbortController();
    const { setHistory, setHistoryLoading } = useChat.getState();
    setHistoryLoading(true);
    fetch(`/api/chats/${encodeURIComponent(chatId)}/messages`, {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    })
      .then(async (r) => {
        if (!r.ok) return; // 404 = new chat
        const parsed = HistorySchema.safeParse(await r.json());
        if (parsed.success) setHistory(parsed.data.messages);
        else
          console.warn(
            "[automind] invalid history payload",
            parsed.error.issues,
          );
      })
      .catch((e: unknown) => {
        if (!(e instanceof DOMException && e.name === "AbortError"))
          console.warn("[automind] history unavailable", e);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setHistoryLoading(false);
      });
    loadCase(chatId, ctrl.signal).catch(() => undefined);
    return () => ctrl.abort();
  }, [chatId]);

  // Keep scrolled to bottom unless the user scrolled up; a new answer is shown from its start (audit F4).
  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };
  const statusCount = pending?.statuses.length ?? 0;
  const seen = useRef(0);
  useLayoutEffect(() => {
    const el = scroller.current;
    const target = scrollTarget(seen.current, messages);
    seen.current = messages.length;
    if (!el || !stick.current) return;
    const msg =
      target.kind === "message"
        ? document.getElementById(messageDomId(target.id))
        : null;
    if (msg) {
      const top =
        msg.getBoundingClientRect().top -
        el.getBoundingClientRect().top +
        el.scrollTop -
        12;
      el.scrollTo({ top, behavior: "smooth" });
      stick.current = false; // reading the answer: later updates must not pull the view down
    } else el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages.length, statusCount, !!pending, !!confirm]);

  const ready = conn === "open" || conn === "mock";
  const busy = pending !== null;
  const empty = messages.length === 0 && !pending;

  const doSend = (text: string): boolean => {
    stick.current = true;
    return send(text);
  };

  return (
    <div className="flex h-full flex-col">
      <Header
        conn={conn}
        onNewChat={newChat}
        canReset={!busy && messages.length > 0}
        onOpenChats={() => setChatsOpen(true)}
      />
      <div className="flex min-h-0 flex-1">
        <main
          ref={scroller}
          onScroll={onScroll}
          className="scroll-thin flex-1 overflow-y-auto overflow-x-hidden"
        >
          <div className="mx-auto w-full max-w-4xl space-y-6 px-3 py-6 sm:px-4">
            {empty ? (
              historyLoading ? (
                <div className="py-24 text-center text-sm text-muted">
                  {t("app.loading")}
                </div>
              ) : (
                <EmptyState onPick={doSend} disabled={!ready || busy} />
              )
            ) : (
              messages.map((m) => <Message key={m.message_id} m={m} />)
            )}
            {pending && (
              <div className="space-y-2 sm:pl-11">
                {pending.grid && Object.keys(pending.grid).length > 0 ? (
                  <ProgressGrid pending={pending} />
                ) : (
                  <StatusTimeline pending={pending} />
                )}
                <CancelButton />
              </div>
            )}
            {confirm && !pending && (
              <div className="sm:pl-11">
                <ConfirmCard req={confirm} />
              </div>
            )}
          </div>
        </main>
        <CaseSidebar />
      </div>
      <CaseSheet />
      <ChatList open={chatsOpen} onClose={() => setChatsOpen(false)} />
      <div className="border-t border-line/40 bg-bg/80 backdrop-blur-md">
        <Composer
          onSend={doSend}
          disabled={!ready || busy}
          busy={busy}
          placeholder={
            busy ? t("composer.busy") : ready ? t("composer.placeholder") : t("composer.connecting")
          }
          shortPlaceholder={
            busy ? t("composer.busy") : ready ? t("composer.placeholder.short") : t("composer.connecting")
          }
        />
      </div>
    </div>
  );
}
