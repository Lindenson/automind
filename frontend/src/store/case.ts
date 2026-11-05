/** Case file REST client (GET/PATCH /api/v1/chats/{id}/case, FR-009) and panel UI state. */
import { create } from "zustand";
import { CaseSchema, type CaseFile } from "../lib/protocol";
import { noteworthy, useChat } from "./chat";

export type CasePatch = Partial<{
  persona: CaseFile["persona"];
  usage: string[];
  budget: Partial<{
    max_eur: number | null;
    intent: "NEW" | "USED" | "ANY" | "UNKNOWN";
  }>;
  running_cost_limit: { amount_eur: number; period: "MONTH" | "YEAR" };
  clear_running_cost_limit: boolean;
  needs: Partial<{
    passengers: number | null;
    luggage: "LOW" | "MEDIUM" | "HIGH";
    towing_kg: number | null;
    daily_km: number | null;
  }>;
  annual_km: number;
  rates_override: Record<string, number | null>;
  depth: CaseFile["depth"];
  weights: Record<string, number>;
  reset_weights: boolean;
  profile: Partial<{
    family: "SINGLE" | "COUPLE" | "FAMILY" | null;
    driving_style: "CALM" | "MIXED" | "SPORTY" | null;
    age_band: "UNDER_25" | "25_40" | "40_60" | "OVER_60" | null;
    home_charging: "YES" | "WORK" | "NO" | null;
  }>;
  ownership_years: number;
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

/** Returns an error message, or null on success. A running turn is not an error: the server queues the edit and
 * applies it when the turn ends (spec 007 J). */
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
    const code = (body as { code?: unknown } | null)?.code;
    if (r.status === 409 && code === "turn_running") return null; // an older server: the next turn uses it
    if (!r.ok) {
      const msg = (body as { message?: unknown } | null)?.message;
      return typeof msg === "string" ? msg : `Could not save (${r.status})`;
    }
    accept(body);
    const rescore = (body as { rescore?: unknown } | null)?.rescore;
    if (rescore === "started" || rescore === "queued")
      useChat.getState().setRescore("updating");
    return null;
  } catch {
    return "Not connected to the AutoMind server";
  }
}

interface PanelState {
  open: boolean;
  setOpen: (v: boolean) => void;
  /** spec 010 FR-038: case changes that arrived while the panel was closed */
  unseen: number;
  /** the field a "Noted … — Edit" link asked to show (a car key or a section), cleared by the panel */
  focus: string | null;
  openAt: (focus: string | null) => void;
}

export const useCasePanel = create<PanelState>((set) => ({
  open: false,
  unseen: 0,
  focus: null,
  setOpen: (open) => set(open ? { open, unseen: 0 } : { open, focus: null }),
  openAt: (focus) => set({ open: true, unseen: 0, focus }),
}));

/** Wide screens show the panel beside the chat (spec 010 FR-038). */
export const WIDE = "(min-width: 1280px)";
const isWide = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(WIDE).matches;

/**
 * The panel speaks up: it opens by itself on the first case file of a chat on a wide screen, and counts the changes
 * that arrive while it is closed (the badge on "Your case").
 */
export function watchCase(wide: () => boolean = isWide): () => void {
  let opened = false;
  return useChat.subscribe((s, prev) => {
    if (s.chatId !== prev.chatId) {
      opened = false;
      useCasePanel.setState({ unseen: 0, focus: null });
      return;
    }
    const cf = s.caseFile;
    if (!cf || cf === prev.caseFile) return;
    const panel = useCasePanel.getState();
    if (!opened && !prev.caseFile && cf.data.cars.length > 0) {
      opened = true;
      if (wide() && !panel.open) {
        panel.setOpen(true);
        return;
      }
    }
    const fresh = !prev.caseFile || cf.version > prev.caseFile.version;
    if (fresh && noteworthy(cf.changes).length > 0 && !useCasePanel.getState().open)
      useCasePanel.setState((p) => ({ unseen: p.unseen + 1 }));
  });
}
