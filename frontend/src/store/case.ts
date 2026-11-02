/** Case file REST client (GET/PATCH /api/v1/chats/{id}/case, FR-009) and panel UI state. */
import { create } from "zustand";
import { CaseSchema, type CaseFile } from "../lib/protocol";
import { useChat } from "./chat";

export type CasePatch = Partial<{
  persona: CaseFile["persona"];
  usage: string[];
  budget: { max_eur: number | null };
  annual_km: number;
  rates_override: Record<string, number | null>;
  depth: CaseFile["depth"];
  weights: Record<string, number>;
  remove_priority: string;
}>;

const url = (chatId: string) =>
  `/api/v1/chats/${encodeURIComponent(chatId)}/case`;

function accept(raw: unknown): void {
  if (typeof raw !== "object" || raw === null) return;
  const r = raw as { version?: unknown; case?: unknown; changes?: unknown };
  const parsed = CaseSchema.safeParse(r.case);
  if (!parsed.success || typeof r.version !== "number") return;
  const changes = Array.isArray(r.changes)
    ? r.changes.filter((x): x is string => typeof x === "string")
    : [];
  const cur = useChat.getState().caseFile;
  if (!cur || cur.version <= r.version)
    useChat
      .getState()
      .setCase({ version: r.version, data: parsed.data, changes });
}

export async function loadCase(
  chatId: string,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(url(chatId), {
    signal,
    headers: { Accept: "application/json" },
  });
  if (r.ok) accept(await r.json());
}

/** Returns an error message, or null on success. */
export async function patchCase(
  chatId: string,
  patch: CasePatch,
): Promise<string | null> {
  try {
    const r = await fetch(url(chatId), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(patch),
    });
    const body: unknown = await r.json().catch(() => null);
    if (!r.ok) {
      const msg = (body as { message?: unknown } | null)?.message;
      return typeof msg === "string" ? msg : `Could not save (${r.status})`;
    }
    accept(body);
    return null;
  } catch {
    return "Not connected to the AutoMind server";
  }
}

interface PanelState {
  open: boolean;
  setOpen: (v: boolean) => void;
}

export const useCasePanel = create<PanelState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}));
