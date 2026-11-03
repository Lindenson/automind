import { create } from "zustand";
import {
  parseServerMsg,
  type CaseFile,
  type ChatMessage,
  type ConfirmRequest,
  type StatusMsg,
  type Usage,
  type ProgressMsg,
} from "../lib/protocol";
import type { ConnState, Transport } from "../lib/transport";
import { loadChatId, saveChatId, uuid } from "../lib/util";

export type ErrorEntry = {
  role: "error";
  message_id: string;
  created_at: string;
  text: string;
};
export type UiMessage = ChatMessage | ErrorEntry;

export type TimedStatus = StatusMsg & { at: number };

export interface PendingTurn {
  userMessageId: string;
  startedAt: number;
  statuses: TimedStatus[];
  grid?: Record<string, ProgressMsg>; // "car_key|area" -> latest state (spec 004 FR-023)
}

export interface CaseState {
  version: number;
  data: CaseFile;
  changes: string[];
}

interface ChatState {
  chatId: string;
  conn: ConnState;
  messages: UiMessage[];
  pending: PendingTurn | null;
  /** current turn id while running or waiting (v2) */
  turnId: string | null;
  confirm: ConfirmRequest | null;
  caseFile: CaseState | null;
  usageByTurn: Record<string, Usage>;
  historyLoading: boolean;
  transport: Transport | null;

  setTransport: (t: Transport | null) => void;
  setConn: (c: ConnState) => void;
  setHistory: (msgs: ChatMessage[]) => void;
  setHistoryLoading: (v: boolean) => void;
  handleRaw: (raw: unknown) => void;
  send: (text: string) => void;
  find: (focusCars: string[], areas: string[], text: string) => void;
  rate: (messageId: string, rating: number, note: string) => void;
  challenge: (carId: string, attribute: string) => void;
  answerConfirm: (choice: string, text?: string) => void;
  cancel: () => void;
  setCase: (c: CaseState) => void;
  newChat: () => void;
  openChat: (id: string) => void;
}

const now = () => new Date().toISOString();

export const useChat = create<ChatState>((set, get) => ({
  chatId: loadChatId(),
  conn: "connecting",
  messages: [],
  pending: null,
  turnId: null,
  confirm: null,
  caseFile: null,
  usageByTurn: {},
  historyLoading: false,
  transport: null,

  setTransport: (transport) => set({ transport }),

  // Protocol v2 replays missed events after a reconnect, so a turn in flight is not lost.
  setConn: (conn) => set({ conn }),

  setCase: (caseFile) => set({ caseFile }),

  setHistory: (msgs) =>
    set((s) => {
      // Only apply history if the user hasn't started chatting meanwhile.
      if (s.messages.length > 0) return {};
      return { messages: msgs };
    }),

  setHistoryLoading: (historyLoading) => set({ historyLoading }),

  handleRaw: (raw) => {
    const msg = parseServerMsg(raw);
    if (!msg) return;
    switch (msg.type) {
      case "progress":
        set((s) => {
          const pending = s.pending ?? { userMessageId: "", startedAt: Date.now(), statuses: [] };
          const grid = { ...(pending.grid ?? {}), [`${msg.car_key}|${msg.area}`]: msg };
          return { pending: { ...pending, grid }, turnId: msg.turn_id ?? s.turnId };
        });
        break;
      case "status":
        set((s) => {
          const entry = { ...msg, at: Date.now() };
          // after a reload the turn is still running server-side: rebuild the progress view
          const pending = s.pending ?? {
            userMessageId: "",
            startedAt: Date.now(),
            statuses: [],
          };
          return {
            pending: { ...pending, statuses: [...pending.statuses, entry] },
            turnId: msg.turn_id ?? s.turnId,
          };
        });
        break;
      case "case_file":
        set((s) =>
          s.caseFile && s.caseFile.version > msg.version
            ? {}
            : {
                caseFile: {
                  version: msg.version,
                  data: msg.case,
                  changes: msg.changes,
                },
              },
        );
        break;
      case "confirm_request":
        set({ confirm: msg, pending: null, turnId: msg.turn_id ?? null });
        break;
      case "usage":
        if (msg.turn_id) {
          const turnId = msg.turn_id;
          set((s) => ({ usageByTurn: { ...s.usageByTurn, [turnId]: msg } }));
        }
        break;
      case "challenge_result": {
        const what: Record<string, string> = {
          CONFIRMED: `confirmed by ${msg.sources.join(", ")}`,
          CORRECTED: `corrected: ${msg.before ?? "—"} → ${msg.after ?? "—"}`,
          REMOVED: `removed (${msg.rejected.map((r) => `${r.source}: ${r.why}`).join("; ")})`,
          UNRESOLVED: "only one source — use “Find it” to search again",
        };
        set((s) => ({
          messages: [
            ...s.messages,
            {
              role: "assistant",
              message_id: uuid(),
              created_at: now(),
              text: `Re-checked **${msg.attribute.replace(/_/g, " ")}**: ${what[msg.outcome]}.`,
              blocks: [],
            },
          ],
        }));
        break;
      }
      case "turn_cancelled":
        set((s) => ({
          pending: null,
          confirm: null,
          turnId: null,
          messages: [
            ...s.messages,
            {
              role: "error",
              message_id: uuid(),
              created_at: now(),
              text: "Stopped.",
            },
          ],
        }));
        break;
      case "user_message_ack":
        set((s) => ({
          messages: s.messages.map((m) =>
            m.role === "user" && m.message_id === msg.message_id
              ? { ...m, created_at: msg.created_at }
              : m,
          ),
        }));
        break;
      case "assistant_message":
        set((s) => {
          if (s.messages.some((m) => m.message_id === msg.message_id))
            return { pending: null, turnId: null };
          return {
            pending: null,
            confirm: null,
            turnId: null,
            messages: [
              ...s.messages,
              {
                role: "assistant",
                message_id: msg.message_id,
                turn_id: msg.turn_id,
                created_at: msg.created_at,
                text: msg.text,
                blocks: msg.blocks,
              },
            ],
          };
        });
        break;
      case "error":
        if (msg.code === "chat_deleted") {
          set({
            pending: null,
            confirm: null,
            messages: [{ role: "error", message_id: uuid(), created_at: now(), text: "This chat was deleted." }],
          });
          break;
        }
        set((s) => ({
          pending: null,
          messages: [
            ...s.messages,
            {
              role: "error",
              message_id: uuid(),
              created_at: now(),
              text: msg.text,
            },
          ],
        }));
        break;
    }
  },

  answerConfirm: (choice, text) => {
    const { transport, confirm } = get();
    if (!transport || !confirm) return;
    if (
      transport.send({
        type: "confirm",
        request_id: confirm.request_id,
        choice,
        text: text ?? null,
      })
    ) {
      set({
        confirm: null,
        pending: { userMessageId: "", startedAt: Date.now(), statuses: [] },
      });
    }
  },

  cancel: () => {
    const { transport, turnId } = get();
    transport?.send({ type: "cancel", turn_id: turnId });
  },

  challenge: (carId, attribute) => {
    get().transport?.send({ type: "challenge", car_id: carId, attribute, text: "this is wrong" });
  },

  rate: (messageId, rating, note) => {
    get().transport?.send({ type: "rating", message_id: messageId, rating, note });
  },

  find: (focusCars, areas, text) => {
    const { transport, pending } = get();
    if (pending || !transport) return;
    const message_id = uuid();
    if (transport.send({ type: "find", focus_cars: focusCars, areas, text, message_id })) {
      set((s) => ({
        messages: [
          ...s.messages,
          { role: "user", message_id, created_at: now(), text, blocks: [] },
        ],
        pending: { userMessageId: message_id, startedAt: Date.now(), statuses: [] },
      }));
    }
  },

  send: (text) => {
    const { transport, pending } = get();
    const trimmed = text.trim();
    if (!trimmed || pending || !transport) return;
    const message_id = uuid();
    const ok = transport.send({
      type: "user_message",
      message_id,
      text: trimmed,
    });
    if (!ok) {
      set((s) => ({
        messages: [
          ...s.messages,
          {
            role: "error",
            message_id: uuid(),
            created_at: now(),
            text: "Not connected to the AutoMind server. Retrying…",
          },
        ],
      }));
      return;
    }
    // a free-text reply while a confirmation is pending resumes that turn (the server interprets it)
    set((s) => ({
      confirm: null,
      messages: [
        ...s.messages,
        {
          role: "user",
          message_id,
          created_at: now(),
          text: trimmed,
          blocks: [],
        },
      ],
      pending: {
        userMessageId: message_id,
        startedAt: Date.now(),
        statuses: [],
      },
    }));
  },

  openChat: (id) => {
    if (id === get().chatId) return;
    const chatId = saveChatId(id);
    set({
      chatId,
      messages: [],
      pending: null,
      turnId: null,
      confirm: null,
      caseFile: null,
      usageByTurn: {},
    });
  },

  newChat: () => {
    const chatId = saveChatId(uuid());
    set({
      chatId,
      messages: [],
      pending: null,
      turnId: null,
      confirm: null,
      caseFile: null,
      usageByTurn: {},
    });
  },
}));
