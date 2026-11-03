import type { ClientMsg } from "./protocol";

export type ConnState = "connecting" | "open" | "closed" | "mock";

export interface TransportHandlers {
  onMessage: (raw: unknown) => void;
  onState: (s: ConnState) => void;
}

export interface Transport {
  send: (msg: ClientMsg) => boolean;
  close: () => void;
}

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
    h.onState("connecting");
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
      if (ev.code === 4410) {
        closed = true; // the chat was deleted: do not reconnect
        h.onState("closed");
        return;
      }
      h.onState("closed");
      schedule();
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
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      const s = ws;
      ws = null;
      s?.close();
    },
  };
}
