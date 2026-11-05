import { create } from "zustand";
import {
  parseServerMsg,
  type CarEditField,
  type CaseFile,
  type ChallengeResult,
  type ChatMessage,
  type ConfirmRequest,
  type StatusMsg,
  type Usage,
  type ProgressMsg,
} from "../lib/protocol";
import type { ConnState, Transport } from "../lib/transport";
import type { Key } from "../i18n/en";
import { asLang, storeLang, storedLang, type Lang } from "../i18n/lang";
import { translate, uiLang } from "../i18n/translate";
import { loadChatId, saveChatId, uuid } from "../lib/util";

/**
 * What kind of failure an error line reports, so it can offer one next step (audit F8):
 * - generic: something broke → try again
 * - overloaded: the AI provider is busy or out of quota → wait a minute, then try again
 * - limit: the research budget is used up → continue with the data already researched
 * - busy: a research is already running → wait for it or stop it
 * - stopped: the user stopped the turn → ask again
 * - offline: the message could not be sent → reconnect now (the text stays in the composer)
 * - gone: the chat cannot be opened here → start a new chat
 */
export type ErrorKind = "generic" | "overloaded" | "limit" | "busy" | "stopped" | "offline" | "gone";

export type ErrorEntry = {
  role: "error";
  message_id: string;
  created_at: string;
  text: string;
  kind?: ErrorKind;
  /** the user's question the error interrupted: "Try again" sends it again */
  retry?: string;
};

/** The kind of a server `error` message: by its code, else by the server's wording (api/ws.py, runner.py). */
export function errorKind(code: string | null | undefined, text: string): ErrorKind {
  const c = (code ?? "").toLowerCase();
  if (c === "chat_deleted" || c === "chat_not_found") return "gone";
  if (c === "busy" || /^busy\b/i.test(text)) return "busy";
  if (/cap|limit|budget|quota_exceeded/.test(c)) return "limit";
  if (/overloaded|out of quota/i.test(text)) return "overloaded";
  return "generic";
}

/** The text of the user's latest question, for "Try again". */
function lastQuestion(messages: UiMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]!;
    if (m.role === "user") return m.text;
  }
  return undefined;
}
/** spec 010 FR-038: a one-line "Noted: … — Edit" entry per set of case changes (this browser only). */
export type NoteEntry = {
  role: "note";
  message_id: string;
  created_at: string;
  turn_id?: string | null;
  changes: string[];
};
export type UiMessage = ChatMessage | ErrorEntry | NoteEntry;

/** Case changes worth a note in the chat: the bookkeeping of the intake is left out. */
const QUIET = [/^asked:/, /^confirmation card shown/, /^card edit not applied/, /^comparison level:/, /: (need|choices|not_found)$/];
export function noteworthy(changes: string[]): string[] {
  return changes.filter((c) => c.trim() && !QUIET.some((r) => r.test(c)));
}

/** spec 010 FR-041: "wrong?" on a value: checking, or the result, keyed by `${car_id}|${attribute}`. */
export type ChallengeState = "checking" | ChallengeResult;
export const challengeKey = (carId: string, attribute: string) => `${carId}|${attribute}`;

export type TimedStatus = StatusMsg & { at: number };

export interface PendingTurn {
  userMessageId: string;
  startedAt: number;
  statuses: TimedStatus[];
  grid?: Record<string, ProgressMsg>; // "car_key|area" -> latest state (spec 004 FR-023)
  /** what the user sent: a question (default), an answer to a confirmation, or an edit of the intake card */
  kind?: "question" | "answer" | "edit";
}

/** spec 010 US2: state of a "bad source" mark, keyed by `${messageId}|${url}`. */
export type BadSourceState = "pending" | "noted" | "ignored";
export const badSourceKey = (messageId: string, url: string) => `${messageId}|${url}`;

export interface BadSourceArgs {
  messageId: string;
  url: string;
  carId?: string;
  attribute?: string;
  area?: string;
}

export interface CaseState {
  version: number;
  data: CaseFile;
  changes: string[];
}

interface ChatState {
  chatId: string;
  conn: ConnState;
  /** reconnect attempts since the connection was lost (audit F8) */
  connAttempt: number;
  messages: UiMessage[];
  pending: PendingTurn | null;
  /** current turn id while running or waiting (v2) */
  turnId: string | null;
  confirm: ConfirmRequest | null;
  caseFile: CaseState | null;
  /** spec 007 J: the report after a panel edit is being recomputed, or that failed */
  rescore: "idle" | "updating" | "failed";
  setRescore: (r: "idle" | "updating" | "failed") => void;
  usageByTurn: Record<string, Usage>;
  historyLoading: boolean;
  transport: Transport | null;

  setTransport: (t: Transport | null) => void;
  setConn: (c: ConnState, attempt?: number) => void;
  /** "Retry now": reconnect without waiting for the backoff */
  reconnect: () => void;
  setHistory: (msgs: ChatMessage[]) => void;
  setHistoryLoading: (v: boolean) => void;
  handleRaw: (raw: unknown) => void;
  /** true when the message went out; false keeps it in the composer (not connected, busy, empty) */
  send: (text: string) => boolean;
  manualLang: Lang | null; // the user's choice in the header (kept in this browser)
  convoLang: Lang | null; // the conversation's language, from the latest reply
  setLang: (lang: Lang | null) => void;
  find: (focusCars: string[], areas: string[], text: string) => void;
  rate: (messageId: string, rating: number, note: string) => void;
  /** spec 010 FR-041: the reason is sent as the text (stored in the feedback) */
  challenge: (carId: string, attribute: string, reason?: string) => void;
  challenges: Record<string, ChallengeState>;
  /** spec 010 FR-037: "Change" on a car; true when it went out */
  carEdit: (carKey: string, field: CarEditField, value?: string) => boolean;
  /** spec 010 US2: "bad source" marks sent in this chat */
  badSources: Record<string, BadSourceState>;
  /** true when the mark went out */
  badSource: (args: BadSourceArgs) => boolean;
  answerConfirm: (choice: string, text?: string) => void;
  editIntake: (carKey: string | null, field: string, value: string) => void;
  cancel: () => void;
  setCase: (c: CaseState) => void;
  newChat: () => void;
  openChat: (id: string) => void;
}

const now = () => new Date().toISOString();

export const useChat = create<ChatState>((set, get) => {
  /** An interface string in the interface language (outside React). */
  const tr = (key: Key, vars?: Record<string, string | number>) =>
    translate(uiLang(get().manualLang, get().convoLang), key, vars);
  return {
    chatId: loadChatId(),
    conn: "connecting",
    connAttempt: 0,
    messages: [],
    manualLang: storedLang(),
    convoLang: null,
    pending: null,
    turnId: null,
    confirm: null,
    caseFile: null,
    rescore: "idle",
    setRescore: (rescore) => set({ rescore }),
    usageByTurn: {},
    badSources: {},
    challenges: {},
    historyLoading: false,
    transport: null,

    setTransport: (transport) => set({ transport }),

    // Protocol v2 replays missed events after a reconnect, so a turn in flight is not lost.
    setConn: (conn, attempt) => set({ conn, connAttempt: conn === "open" || conn === "mock" ? 0 : attempt ?? 0 }),

    reconnect: () => get().transport?.reconnect?.(),

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
            const pending = s.pending ?? {
              userMessageId: "",
              startedAt: Date.now(),
              statuses: [],
            };
            const grid = {
              ...(pending.grid ?? {}),
              [`${msg.car_key}|${msg.area}`]: msg,
            };
            return {
              pending: { ...pending, grid },
              turnId: msg.turn_id ?? s.turnId,
            };
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
          set((s) => {
            if (s.caseFile && s.caseFile.version > msg.version) return {};
            const caseFile = { version: msg.version, data: msg.case, changes: msg.changes };
            const fresh = !s.caseFile || msg.version > s.caseFile.version;
            const changes = fresh ? noteworthy(msg.changes) : [];
            if (!changes.length) return { caseFile };
            // one note per turn: later change sets of the same turn join it
            const last = s.messages[s.messages.length - 1];
            if (last?.role === "note" && (last.turn_id ?? null) === (msg.turn_id ?? null)) {
              const merged = [...last.changes, ...changes.filter((c) => !last.changes.includes(c))];
              return { caseFile, messages: [...s.messages.slice(0, -1), { ...last, changes: merged }] };
            }
            const note: NoteEntry = { role: "note", message_id: uuid(), created_at: now(), turn_id: msg.turn_id, changes };
            return { caseFile, messages: [...s.messages, note] };
          });
          break;
        case "agreed":
          set((s) =>
            s.messages.some((m) => m.message_id === msg.message_id)
              ? {}
              : {
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
          // shown in the challenged cell (spec 010 FR-041); a result for a value no cell shows still gets a line
          const key = challengeKey(msg.car_id ?? "", msg.attribute);
          set((s) => {
            if (s.challenges[key] !== undefined) return { challenges: { ...s.challenges, [key]: msg } };
            const what: Record<string, string> = {
              CONFIRMED: tr("challenge.CONFIRMED", { sources: msg.sources.join(", ") }),
              CORRECTED: tr("challenge.CORRECTED", { before: msg.before ?? "—", after: msg.after ?? "—" }),
              REMOVED: tr("challenge.REMOVED", { why: msg.rejected.map((r) => `${r.source}: ${r.why}`).join("; ") }),
              UNRESOLVED: tr("challenge.UNRESOLVED"),
            };
            return {
              challenges: { ...s.challenges, [key]: msg },
              messages: [
                ...s.messages,
                {
                  role: "assistant",
                  message_id: uuid(),
                  created_at: now(),
                  text: tr("challenge.result", { attr: msg.attribute.replace(/_/g, " "), what: what[msg.outcome] ?? "" }),
                  blocks: [],
                },
              ],
            };
          });
          break;
        }
        case "feedback_ack": {
          // the ack names the url only: settle every pending mark of it
          const state: BadSourceState = msg.ignored ? "ignored" : "noted";
          set((s) => {
            const badSources = { ...s.badSources };
            let changed = false;
            for (const [k, v] of Object.entries(badSources)) {
              if (v === "pending" && k.endsWith(`|${msg.url}`)) {
                badSources[k] = state;
                changed = true;
              }
            }
            return changed ? { badSources } : {};
          });
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
                text: tr("chat.stopped"),
                kind: "stopped",
                retry: lastQuestion(s.messages),
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
        case "rescore_failed":
          set({ rescore: "failed", pending: null, turnId: null });
          break;
        case "assistant_message":
          set((s) => {
            if (s.messages.some((m) => m.message_id === msg.message_id))
              return { pending: null, turnId: null, rescore: "idle" };
            return {
              rescore: "idle",
              pending: null,
              confirm: null,
              turnId: null,
              convoLang: asLang(msg.language) ?? s.convoLang,
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
        case "error": {
          const kind = errorKind(msg.code, msg.text);
          if (kind === "gone") {
            set({
              pending: null,
              confirm: null,
              messages: [
                {
                  role: "error",
                  message_id: uuid(),
                  created_at: now(),
                  text: tr(msg.code === "chat_deleted" ? "chat.deleted" : "chat.notFound"),
                  kind,
                },
              ],
            });
            break;
          }
          set((s) => ({
            // "busy": the running research goes on, so its progress stays on screen
            pending: kind === "busy" ? s.pending : null,
            messages: [
              ...s.messages,
              {
                role: "error",
                message_id: uuid(),
                created_at: now(),
                text: msg.text,
                kind,
                retry: lastQuestion(s.messages),
              },
            ],
          }));
          break;
        }
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
          pending: { userMessageId: "", startedAt: Date.now(), statuses: [], kind: "answer" },
        });
      }
    },

    editIntake: (carKey, field, value) => {
      const { transport, confirm } = get();
      if (!transport || !confirm) return;
      if (
        transport.send({
          type: "intake_edit",
          request_id: confirm.request_id,
          car_key: carKey,
          field,
          value,
        })
      ) {
        set({
          confirm: null,
          pending: { userMessageId: "", startedAt: Date.now(), statuses: [], kind: "edit" },
        });
      }
    },

    cancel: () => {
      const { transport, turnId } = get();
      transport?.send({ type: "cancel", turn_id: turnId });
    },

    challenge: (carId, attribute, reason) => {
      const ok = get().transport?.send({
        type: "challenge",
        car_id: carId,
        attribute,
        text: reason?.trim() || "this is wrong",
      });
      if (ok)
        set((s) => ({ challenges: { ...s.challenges, [challengeKey(carId, attribute)]: "checking" } }));
    },

    carEdit: (carKey, field, value) => {
      const { transport, pending } = get();
      if (!transport || pending) return false;
      const message_id = uuid();
      const ok = transport.send({
        type: "car_edit",
        message_id,
        car_key: carKey,
        field,
        ...(value?.trim() ? { value: value.trim() } : {}),
      });
      if (ok)
        set({
          confirm: null,
          pending: { userMessageId: message_id, startedAt: Date.now(), statuses: [], kind: "edit" },
        });
      return ok;
    },

    badSource: ({ messageId, url, carId, attribute, area }) => {
      const { transport, badSources } = get();
      if (!transport || !messageId || !url) return false;
      const key = badSourceKey(messageId, url);
      if (badSources[key]) return false;
      const ok = transport.send({
        type: "bad_source",
        message_id: messageId,
        url,
        ...(carId ? { car_id: carId } : {}),
        ...(attribute ? { attribute } : {}),
        ...(area ? { area } : {}),
      });
      if (ok) set((s) => ({ badSources: { ...s.badSources, [key]: "pending" } }));
      return ok;
    },

    setLang: (lang) => {
      storeLang(lang);
      set({ manualLang: lang });
    },

    rate: (messageId, rating, note) => {
      get().transport?.send({
        type: "rating",
        message_id: messageId,
        rating,
        note,
      });
    },

    find: (focusCars, areas, text) => {
      const { transport, pending } = get();
      if (pending || !transport) return;
      const message_id = uuid();
      if (
        transport.send({
          type: "find",
          focus_cars: focusCars,
          areas,
          text,
          message_id,
        })
      ) {
        set((s) => ({
          messages: [
            ...s.messages,
            { role: "user", message_id, created_at: now(), text, blocks: [] },
          ],
          pending: {
            userMessageId: message_id,
            startedAt: Date.now(),
            statuses: [],
          },
        }));
      }
    },

    send: (text) => {
      const { transport, pending } = get();
      const trimmed = text.trim();
      if (!trimmed || pending || !transport) return false;
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
              text: tr("chat.notConnected"),
              kind: "offline",
            },
          ],
        }));
        return false;
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
      return true;
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
        badSources: {},
        challenges: {},
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
        badSources: {},
        challenges: {},
      });
    },
  };
});
