/** Spec 010 T044: state of the admin page (zustand). */
import { create } from "zustand";
import { ForbiddenError, adminApi, setToken } from "./api";
import type { ProblemDetail, ProblemItem, StatusPatch } from "./schemas";

export type AdminTab = "problems" | "sources";

interface AdminState {
  tab: AdminTab;
  /** The server refused the token: show the token prompt. */
  needToken: boolean;
  problems: ProblemItem[] | null;
  loading: boolean;
  error: string | null;
  openId: string | null;
  detail: ProblemDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  saving: boolean;

  setTab: (tab: AdminTab) => void;
  submitToken: (token: string) => Promise<void>;
  loadProblems: () => Promise<void>;
  openProblem: (id: string) => Promise<void>;
  closeProblem: () => void;
  setStatus: (id: string, patch: StatusPatch) => Promise<boolean>;
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

export const useAdmin = create<AdminState>((set, get) => {
  /** A 403 anywhere switches to the token prompt; other errors come back as text. */
  const fail = (e: unknown): string | null => {
    if (e instanceof ForbiddenError) {
      set({ needToken: true, openId: null, detail: null });
      return null;
    }
    return message(e);
  };

  return {
    tab: "problems",
    needToken: false,
    problems: null,
    loading: false,
    error: null,
    openId: null,
    detail: null,
    detailLoading: false,
    detailError: null,
    saving: false,

    setTab: (tab) => set({ tab }),

    submitToken: async (token) => {
      setToken(token.trim());
      set({ needToken: false, error: null });
      await get().loadProblems();
    },

    loadProblems: async () => {
      set({ loading: true, error: null });
      try {
        const problems = await adminApi.problems();
        set({ problems, loading: false });
      } catch (e) {
        set({ loading: false, error: fail(e) });
      }
    },

    openProblem: async (id) => {
      set({ openId: id, detail: null, detailLoading: true, detailError: null });
      try {
        const detail = await adminApi.problem(id);
        if (get().openId === id) set({ detail, detailLoading: false });
      } catch (e) {
        const err = fail(e);
        if (get().openId === id) set({ detailLoading: false, detailError: err });
      }
    },

    closeProblem: () => set({ openId: null, detail: null, detailError: null, detailLoading: false }),

    setStatus: async (id, patch) => {
      set({ saving: true, detailError: null });
      try {
        await adminApi.setStatus(id, patch);
        set({ saving: false });
        const detail = await adminApi.problem(id).catch(() => null);
        if (detail && get().openId === id) set({ detail });
        void get().loadProblems();
        return true;
      } catch (e) {
        set({ saving: false, detailError: fail(e) });
        return false;
      }
    },
  };
});
