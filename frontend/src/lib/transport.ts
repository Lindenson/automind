import type { ClientMsg } from "./protocol";

/** `gone`: the server refused this chat for good (deleted, another browser's, cross-site): no reconnect (audit F8). */
export type ConnState = "connecting" | "open" | "closed" | "gone" | "mock";

export interface TransportHandlers {
  onMessage: (raw: unknown) => void;
  /** `attempt`: reconnect attempts since the connection was lost (0 when connected) */
  onState: (s: ConnState, attempt?: number) => void;
}

export interface Transport {
  send: (msg: ClientMsg) => boolean;
  close: () => void;
  /** Reconnect now instead of waiting for the next backoff step ("Retry now", audit F8). */
  reconnect?: () => void;
}

/** WebSocket close codes after which the chat cannot be opened again (api/ws.py, api/app.py). */
export const GONE_CODES = new Set([4403, 4404, 4410]);

const seqKey = (chatId: string) => `automind:last_seq:${chatId}`;

/** Last event seq seen for a chat (sessionStorage, so a reload replays only what was missed). */
export function loadLastSeq(chatId: string): number {
  try {
    return Number(sessionStorage.getItem(seqKey(chatId)) ?? 0) || 0;
  } catch {
    return 0;
  }
}

/** Forget the replay position of a deleted chat. */
export function clearLastSeq(chatId: string): void {
  try {
    sessionStorage.removeItem(seqKey(chatId));
  } catch {
    /* storage unavailable */
  }
}

function saveLastSeq(chatId: string, seq: number): void {
  try {
    sessionStorage.setItem(seqKey(chatId), String(seq));
  } catch {
    /* storage unavailable: replay falls back to in-memory seq */
  }
}

/**
 * WebSocket transport (protocol v2) with exponential backoff reconnect.
 * On every (re)connect it sends `hello{last_seq}` so the server replays missed events.
 */
export function createWsTransport(chatId: string, h: TransportHandlers, initialSeq = 0): Transport {
  let lastSeq = initialSeq;
  let ws: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const url = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/chat/${encodeURIComponent(chatId)}`;

  const connect = () => {
    if (closed) return;
    h.onState("connecting", attempt);
    let sock: WebSocket;
    try {
      sock = new WebSocket(url);
    } catch {
      schedule();
      return;
    }
    ws = sock;
    sock.onopen = () => {
      attempt = 0;
      sock.send(JSON.stringify({ type: "hello", last_seq: lastSeq }));
      h.onState("open");
    };
    sock.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let data: unknown;
      try {
        data = JSON.parse(ev.data);
      } catch {
        console.warn("[automind] non-JSON message ignored");
        return;
      }
      const seq = typeof data === "object" && data !== null ? (data as { seq?: unknown }).seq : undefined;
      if (typeof seq === "number") {
        if (seq <= lastSeq) return; // duplicate after replay
        lastSeq = seq;
        saveLastSeq(chatId, seq);
      }
      h.onMessage(data);
    };
    sock.onclose = (ev) => {
      if (ws !== sock) return;
      ws = null;
      if (closed) return;
      if (GONE_CODES.has(ev.code)) {
        closed = true; // deleted, another browser's chat, or refused: do not reconnect
        h.onState("gone");
        return;
      }
      schedule();
      h.onState("closed", attempt);
    };
    sock.onerror = () => {
      /* onclose follows */
    };
  };

  const schedule = () => {
    if (closed) return;
    const base = Math.min(10_000, 500 * 2 ** attempt);
    attempt += 1;
    timer = setTimeout(connect, base * (0.75 + Math.random() * 0.5));
  };

  connect();

  return {
    send(msg) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify(msg));
      return true;
    },
    reconnect() {
      if (closed || ws) return;
      if (timer) clearTimeout(timer);
      timer = null;
      connect();
    },
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      const s = ws;
      ws = null;
      s?.close();
    },
  };
}
